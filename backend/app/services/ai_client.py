"""The only module that talks to the Anthropic API.

The rest of the import code sees a small interface (LLMClient) and two kinds of failure:
  * AIUnavailable: the AI cannot be used right now (no key, no credit, rate limit, outage,
    daily limit). The import can still save what the page's own markup provides.
  * AIOutputError: the AI answered but the answer is unusable (refusal, cut off, not valid).
"""

import logging
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class AIOutputError(Exception):
    pass


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    request_id: str | None


@dataclass(frozen=True)
class AIResponse[T]:
    parsed: T
    usage: AIUsage


class LLMClient(Protocol):
    model: str

    def parse(self, *, system: str, messages: list[dict], schema: type[T]) -> AIResponse[T]: ...


class ClaudeClient:
    """Structured extraction with one `messages.parse` call: the schema is sent as the output
    format, so the reply is valid JSON of exactly that shape (no hand-written JSON parsing)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float,
        max_output_tokens: int,
        max_retries: int = 2,
        http_client=None,
    ):
        self.model = model
        self._max_output_tokens = max_output_tokens
        # max_retries: the SDK already retries connection errors, 408/409/429 and 5xx twice
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=max_retries, http_client=http_client
        )

    def parse(self, *, system: str, messages: list[dict], schema: type[T]) -> AIResponse[T]:
        try:
            message = self._client.messages.parse(
                model=self.model,
                max_tokens=self._max_output_tokens,
                system=system,
                messages=messages,
                output_format=schema,
                # Reading and sorting text needs little reasoning: low effort keeps it cheap.
                output_config={"effort": "low"},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            logger.error("Anthropic rejected the API key (invalid, revoked or without permission)")
            raise AIUnavailable(
                "ai_not_configured", "The AI key is invalid or not allowed."
            ) from None
        except anthropic.BadRequestError as exc:
            # "credit balance is too low" is a 400; other 400s mean our own request is wrong.
            logger.error("Anthropic rejected the request: %s", exc.message)
            no_credit = "credit balance" in str(exc.message).lower()
            raise AIUnavailable(
                "ai_no_credit" if no_credit else "ai_error",
                "The AI account has no credit left."
                if no_credit
                else "The AI request was rejected.",
            ) from None
        except anthropic.NotFoundError:
            logger.error("Anthropic model %r was not found", self.model)
            raise AIUnavailable("ai_error", "The configured AI model does not exist.") from None
        except anthropic.RateLimitError:
            raise AIUnavailable(
                "ai_rate_limited", "The AI service is busy, try again later."
            ) from None
        except (anthropic.APITimeoutError, anthropic.APIConnectionError):
            raise AIUnavailable("ai_unreachable", "The AI service could not be reached.") from None
        except anthropic.APIStatusError as exc:
            logger.error("Anthropic API error %s", exc.status_code)
            raise AIUnavailable("ai_error", "The AI service had an error.") from None
        except ValidationError as exc:
            raise AIOutputError(f"the answer did not match the expected structure: {exc}") from None

        if message.stop_reason == "refusal":
            raise AIOutputError("the AI declined to process this page")
        if message.stop_reason == "max_tokens":
            raise AIOutputError("the recipe is too long for the AI answer limit")
        if message.parsed_output is None:
            raise AIOutputError("the AI returned no structured answer")

        usage = message.usage
        return AIResponse(
            parsed=message.parsed_output,
            usage=AIUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                request_id=getattr(message, "_request_id", None),
            ),
        )
