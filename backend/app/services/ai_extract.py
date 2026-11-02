"""Run the AI on a recipe: cache, daily limit, check the answer, one correction attempt.

What is guaranteed where:
  * the SHAPE of the answer by structured outputs (the API will not return anything else);
  * the MEANING by validate_* below (right number of lines, no invented ingredients, ...);
  * COST by the Redis cache (the same input is never paid for twice), a per-user daily limit
    and log lines / counters for every call.
A result is cached only after it passed validation.
"""

import hashlib
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.schemas.ai import AIFullRecipe, AIIngredient, AIRefinement
from app.services import ai_prompts
from app.services.ai_client import AIOutputError, AIUnavailable, AIUsage, LLMClient
from app.services.limits import RateLimitExceeded, check_rate_limit

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_STEPS = 100
MAX_INGREDIENT_LINES = 200
_DAY = 24 * 3600
_WORDS = re.compile(r"\w+")
_MIN_GROUNDED = 0.7  # share of an ingredient line's words that must occur on the page
_IMPERIAL = re.compile(
    "(?<![A-Za-z])(pounds?|lbs?|ounces?|oz|pints?|quarts?|gallons?|sticks?)(?![A-Za-z])",
    re.IGNORECASE,
)
_FIRST_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_METRIC = ("g", "kg", "ml", "l")


class AIInvalidOutput(Exception):
    """The AI answered, twice, with something that does not make sense."""


class NoRecipeOnPage(Exception):
    """The AI read the page and found no recipe in it."""


# --- checking the meaning of an answer (pure functions, easy to test) ---
def _unconverted_imperial(item: AIIngredient) -> bool:
    """'1 pound ...' answered with 1 g: the number was copied, the unit was not converted."""
    if item.unit not in _METRIC or item.quantity is None or not _IMPERIAL.search(item.raw_text):
        return False
    match = _FIRST_NUMBER.search(item.raw_text)
    return match is not None and abs(float(match.group().replace(",", ".")) - item.quantity) < 1e-6


def _common_problems(ai: AIRefinement, expected_lines: int | None) -> list[str]:
    problems: list[str] = []
    numbers = sorted(i.line for i in ai.ingredients)
    if expected_lines is not None and numbers != list(range(expected_lines)):
        problems.append(
            "ingredients must contain exactly one entry per line, numbered "
            f"0 to {expected_lines - 1}"
        )
    elif expected_lines is None and numbers != list(range(len(numbers))):
        problems.append("ingredient line numbers must be 0, 1, 2, ... without gaps or repeats")
    if len(ai.ingredients) > MAX_INGREDIENT_LINES:
        problems.append(f"at most {MAX_INGREDIENT_LINES} ingredient lines are allowed")
    if len(ai.steps) > MAX_STEPS:
        problems.append(f"at most {MAX_STEPS} steps are allowed")
    unconverted = [i.line for i in ai.ingredients if _unconverted_imperial(i)]
    if unconverted:
        problems.append(
            f"lines {unconverted} use pounds/ounces/pints/...: convert them to grams or "
            "millilitres (1 pound = 454 g, 1 ounce = 28 g) instead of copying the number"
        )
    if any(not step.strip() for step in ai.steps):
        problems.append("steps must not contain empty items")
    bad = [
        i.line for i in ai.ingredients if i.quantity is not None and not 0 <= i.quantity <= 100_000
    ]
    if bad:
        problems.append(f"quantity must be between 0 and 100000 (lines {bad})")
    return problems


def validate_refinement(ai: AIRefinement, *, ingredient_lines: int, step_lines: int) -> list[str]:
    problems = _common_problems(ai, ingredient_lines)
    if step_lines and not ai.steps:
        problems.append("steps must not be empty: the source has preparation steps")
    return problems


def _words(text: str) -> list[str]:
    return _WORDS.findall(text.casefold())


def validate_full_recipe(ai: AIFullRecipe, page_text: str) -> list[str]:
    problems = _common_problems(ai, None)
    if not (ai.title or "").strip():
        problems.append("title is required")
    if not ai.ingredients:
        problems.append("a recipe needs at least one ingredient line")
    if not ai.steps:
        problems.append("a recipe needs at least one step")
    # Anti-invention check: ingredient lines must be COPIED from the page.
    page_words = set(_words(page_text))
    invented = []
    for item in ai.ingredients:
        words = _words(item.raw_text)
        if not words or sum(w in page_words for w in words) / len(words) < _MIN_GROUNDED:
            invented.append(item.line)
    if invented:
        problems.append(
            f"raw_text of lines {invented} was not found on the page; copy ingredient lines "
            "exactly as written and do not invent any"
        )
    return problems


# --- running ---
class RecipeAI:
    def __init__(self, client: LLMClient | None, redis: Redis):
        self._client = client
        self._redis = redis

    @property
    def configured(self) -> bool:
        return self._client is not None

    def refine(
        self, user_id: int, ingredient_lines: list[str], step_lines: list[str]
    ) -> AIRefinement:
        """Page with structured data: take the ingredient lines apart and tidy the steps."""
        message = ai_prompts.structured_user_message(ingredient_lines, step_lines)
        return self._run(
            user_id,
            mode="structured",
            user_message=message,
            schema=AIRefinement,
            validate=lambda ai: validate_refinement(
                ai, ingredient_lines=len(ingredient_lines), step_lines=len(step_lines)
            ),
        )

    def extract_page(self, user_id: int, page_text: str, page_url: str) -> AIFullRecipe:
        """Page without structured data: read the whole recipe from its text."""
        message = ai_prompts.page_user_message(page_text, page_url)
        recipe = self._run(
            user_id,
            mode="page",
            user_message=message,
            schema=AIFullRecipe,
            validate=lambda ai: (
                [] if not ai.contains_recipe else validate_full_recipe(ai, page_text)
            ),
        )
        if not recipe.contains_recipe:
            raise NoRecipeOnPage
        return recipe

    # --- internals ---
    def _cache_key(self, mode: str, user_message: str) -> str:
        raw = f"{ai_prompts.PROMPT_VERSION}|{self._model}|{mode}|{user_message}"
        return "ai:v1:" + hashlib.sha256(raw.encode()).hexdigest()

    @property
    def _model(self) -> str:
        return self._client.model if self._client else get_settings().ai_model

    def _run(
        self,
        user_id: int,
        *,
        mode: str,
        user_message: str,
        schema: type[T],
        validate: Callable[[T], list[str]],
    ) -> T:
        settings = get_settings()
        key = self._cache_key(mode, user_message)
        cached = self._cache_get(key, schema)
        if cached is not None:
            logger.info("ai_cache_hit mode=%s", mode)
            return cached

        if self._client is None:
            raise AIUnavailable("ai_not_configured", "AI import is not configured on this server.")
        try:
            check_rate_limit(self._redis, f"ai:{user_id}", settings.ai_daily_limit_per_user, _DAY)
        except RateLimitExceeded:
            raise AIUnavailable(
                "ai_limit_reached",
                f"The daily limit of {settings.ai_daily_limit_per_user} AI imports is reached.",
            ) from None
        except RedisError:
            logger.exception("AI limiter unavailable")
            raise AIUnavailable("ai_unavailable", "AI import is temporarily unavailable.") from None

        system = ai_prompts.system_prompt(mode)
        messages: list[dict] = [{"role": "user", "content": user_message}]
        problems: list[str] = []
        for attempt in (1, 2):
            try:
                response = self._client.parse(system=system, messages=messages, schema=schema)
            except AIOutputError as exc:
                raise AIInvalidOutput(str(exc)) from None
            self._record_usage(mode, attempt, response.usage)

            problems = validate(response.parsed)
            if not problems:
                self._cache_set(key, response.parsed)
                return response.parsed
            logger.warning(
                "ai_invalid_output mode=%s attempt=%d problems=%s", mode, attempt, problems
            )
            messages = [
                *messages,
                {"role": "assistant", "content": response.parsed.model_dump_json()},
                {"role": "user", "content": ai_prompts.correction_message(problems)},
            ]
        raise AIInvalidOutput("; ".join(problems))

    def _cache_get(self, key: str, schema: type[T]) -> T | None:
        try:
            raw = self._redis.get(key)
            return schema.model_validate_json(raw) if raw else None
        except (RedisError, ValidationError):
            logger.warning("AI cache read failed", exc_info=True)
            return None

    def _cache_set(self, key: str, value: BaseModel) -> None:
        try:
            self._redis.set(key, value.model_dump_json(), ex=get_settings().ai_cache_ttl_sec)
        except RedisError:
            logger.warning("AI cache write failed", exc_info=True)

    def _record_usage(self, mode: str, attempt: int, usage: AIUsage) -> None:
        """One log line per API call, plus per-day counters in Redis (calls and tokens)."""
        logger.info(
            "ai_call model=%s mode=%s attempt=%d input_tokens=%d output_tokens=%d "
            "cache_read_tokens=%d request_id=%s",
            self._model, mode, attempt, usage.input_tokens, usage.output_tokens,
            usage.cache_read_tokens, usage.request_id,
        )  # fmt: skip
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        try:
            with self._redis.pipeline(transaction=True) as pipe:
                for name, amount in (
                    ("calls", 1),
                    ("input_tokens", usage.input_tokens),
                    ("output_tokens", usage.output_tokens),
                ):
                    pipe.incrby(f"ai:{name}:{day}", amount)
                    pipe.expire(f"ai:{name}:{day}", 40 * _DAY)
                pipe.execute()
        except RedisError:
            logger.warning("AI counters could not be updated", exc_info=True)
