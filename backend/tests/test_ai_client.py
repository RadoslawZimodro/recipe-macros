"""ClaudeClient against a fake Anthropic API: what we send, how answers and errors are handled.
httpx2.MockTransport plays the API, so the real SDK code runs (request building, schema
transformation, response parsing) without network access or cost."""

import json

import httpx2
import pytest

from app.schemas.ai import AIRefinement
from app.services.ai_client import AIOutputError, AIUnavailable, ClaudeClient
from tests.fakes import pl_flat_refinement


def message_json(text, *, stop_reason="end_turn", input_tokens=1200, output_tokens=400):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def error_json(kind, message):
    return {"type": "error", "error": {"type": kind, "message": message}}


def make_client(handler):
    return ClaudeClient(
        "sk-ant-test",
        "claude-haiku-5-5",
        timeout=5,
        max_output_tokens=2000,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def ask(client):
    return client.parse(
        system="SYSTEM", messages=[{"role": "user", "content": "hello"}], schema=AIRefinement
    )


GOOD = pl_flat_refinement().model_dump_json()


def test_request_carries_model_schema_low_effort_and_no_sampling_parameters():
    seen = {}

    def handler(request):
        seen["request"] = request
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=message_json(GOOD))

    ask(make_client(handler))

    request, body = seen["request"], seen["body"]
    assert request.method == "POST" and request.url.path == "/v1/messages"
    assert request.headers["authorization"] == "Bearer sk-ant-test"
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 2000
    assert body["system"] == "SYSTEM"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    # models that reject non-default sampling parameters must never be sent them
    assert not {"temperature", "top_p", "top_k"} & body.keys()
    assert "tool_choice" not in body  # forced tool use is rejected by the newest models
    assert "stream" not in body or body["stream"] is False


def test_the_schema_sent_to_the_api_restricts_units_and_forbids_extra_fields():
    seen = {}

    def handler(request):
        seen["schema"] = json.loads(request.content)["output_config"]["format"]["schema"]
        return httpx2.Response(200, json=message_json(GOOD))

    ask(make_client(handler))

    schema_text = json.dumps(seen["schema"])
    for unit in ("tbsp", "pinch", "clove"):
        assert f'"{unit}"' in schema_text  # the allowed units are an enum in the schema
    assert '"additionalProperties": false' in schema_text


def test_a_good_answer_is_parsed_into_the_model_with_usage():
    client = make_client(lambda request: httpx2.Response(200, json=message_json(GOOD)))

    response = ask(client)

    assert isinstance(response.parsed, AIRefinement)
    assert len(response.parsed.ingredients) == 7 and response.parsed.ingredients[0].unit == "g"
    assert response.usage.input_tokens == 1200 and response.usage.output_tokens == 400
    assert response.usage.cache_read_tokens == 0


@pytest.mark.parametrize(
    ("status", "kind", "message", "code"),
    [
        (401, "authentication_error", "invalid x-api-key", "ai_not_configured"),
        (403, "permission_error", "not allowed", "ai_not_configured"),
        (400, "invalid_request_error", "Your credit balance is too low", "ai_no_credit"),
        (400, "invalid_request_error", "something is wrong with the request", "ai_error"),
        (404, "not_found_error", "model: nope", "ai_error"),
        (429, "rate_limit_error", "slow down", "ai_rate_limited"),
        (500, "api_error", "internal", "ai_error"),
        (529, "overloaded_error", "overloaded", "ai_error"),
    ],
)
def test_api_errors_become_ai_unavailable_with_a_stable_code(status, kind, message, code):
    client = make_client(lambda request: httpx2.Response(status, json=error_json(kind, message)))

    with pytest.raises(AIUnavailable) as exc:
        ask(client)

    assert exc.value.code == code


def test_error_messages_never_leak_the_key_or_the_raw_api_error():
    client = make_client(
        lambda request: httpx2.Response(
            401, json=error_json("authentication_error", "invalid x-api-key sk-ant-test")
        )
    )

    with pytest.raises(AIUnavailable) as exc:
        ask(client)

    assert "sk-ant" not in exc.value.message


@pytest.mark.parametrize("error", [httpx2.ConnectError("down"), httpx2.ReadTimeout("slow")])
def test_network_failures_become_ai_unavailable(error):
    def handler(request):
        raise error

    with pytest.raises(AIUnavailable) as exc:
        ask(make_client(handler))

    assert exc.value.code == "ai_unreachable"


def test_the_sdk_retries_transient_errors_before_giving_up():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx2.Response(529, json=error_json("overloaded_error", "overloaded"))
        return httpx2.Response(200, json=message_json(GOOD))

    client = ClaudeClient(
        "sk-ant-test",
        "claude-haiku-5-5",
        timeout=5,
        max_output_tokens=2000,
        max_retries=2,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )

    assert ask(client).parsed.steps and len(calls) == 2


def test_a_refusal_is_an_output_error():
    refusal = message_json("", stop_reason="refusal") | {"content": []}
    client = make_client(lambda request: httpx2.Response(200, json=refusal))

    with pytest.raises(AIOutputError, match="declined"):
        ask(client)


def test_an_answer_cut_off_at_the_token_limit_is_an_output_error():
    cut_off = message_json(GOOD[:60], stop_reason="max_tokens")  # the JSON stops mid-way
    client = make_client(lambda request: httpx2.Response(200, json=cut_off))

    with pytest.raises(AIOutputError):
        ask(client)


@pytest.mark.parametrize("text", ["not json at all", '{"steps": "wrong type"}', "{}"])
def test_an_answer_that_does_not_fit_the_schema_is_an_output_error(text):
    client = make_client(lambda request: httpx2.Response(200, json=message_json(text)))

    with pytest.raises((AIOutputError, AIUnavailable)) as exc:
        ask(client)

    assert isinstance(exc.value, AIOutputError)
