"""Import a recipe from a link: normalize, look up, fetch, extract, save.

Flow: the address is normalized; if the user already has that recipe it is returned as is
(no network). Otherwise the per-user import budget is checked, the page is fetched through
the SSRF-safe fetcher, the schema.org recipe is extracted from its JSON-LD and saved with a
single `INSERT ... ON CONFLICT DO UPDATE` (app/sql/upsert_imported_recipe.sql).
"""

import json
import logging
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RecipeIngredient, RecipeStep
from app.schemas.recipe import RecipeOut
from app.services.jsonld import ExtractedRecipe, extract_recipe
from app.services.limits import RateLimitExceeded, check_rate_limit
from app.services.page_fetcher import PageFetcher
from app.services.recipes import build_children, get_recipe
from app.services.safe_fetch import FetchError
from app.services.sql import load_sql
from app.services.urls import UrlError, normalize_url

logger = logging.getLogger(__name__)

# HTTP status per error code. 422: this address cannot be imported (the user can pick another);
# 5xx: the other site or our infrastructure is the problem and a retry may help.
STATUS_BY_CODE = {
    "invalid_url": 422,
    "unsupported_site": 422,
    "blocked_address": 422,
    "dns_failure": 422,
    "robots_disallowed": 422,
    "access_denied": 422,
    "not_found": 422,
    "not_html": 422,
    "too_large": 422,
    "too_many_redirects": 422,
    "no_recipe_data": 422,
    "rate_limited": 429,
    "upstream_error": 502,
    "robots_unavailable": 502,
    "timeout": 504,
    "service_unavailable": 503,
}


class ImportFailed(Exception):
    """The import cannot be completed. `code` is stable for clients, `message` is readable."""

    def __init__(self, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after

    @property
    def status_code(self) -> int:
        return STATUS_BY_CODE.get(self.code, 502)


@dataclass(frozen=True)
class ImportResult:
    recipe: RecipeOut
    status: str  # "created" | "existing" | "refreshed"


def _enforce_rate_limit(redis: Redis, user_id: int) -> None:
    limit = get_settings().import_rate_limit_per_min
    try:
        check_rate_limit(redis, f"import:{user_id}", limit, window_sec=60)
    except RateLimitExceeded as exc:
        raise ImportFailed(
            "rate_limited",
            f"Too many imports: at most {limit} per minute. Try again shortly.",
            retry_after=exc.retry_after,
        ) from None
    except RedisError:
        # Fail closed: the limit protects other sites from being hammered through us.
        logger.exception("Import rate limiter unavailable")
        raise ImportFailed(
            "service_unavailable", "Import is temporarily unavailable, try again later."
        ) from None


def _save(session: Session, user_id: int, extracted: ExtractedRecipe) -> tuple[int, bool]:
    """Upsert the recipe row, then replace its steps and ingredient lines. One transaction."""
    recipe = extracted.recipe
    row = session.execute(
        load_sql("upsert_imported_recipe.sql"),
        {
            "user_id": user_id,
            "title": recipe.title,
            "description": recipe.description,
            "source_url": recipe.source_url,
            "servings": recipe.servings,
            "image_url": recipe.image_url,
            "prep_time_min": recipe.prep_time_min,
            "cook_time_min": recipe.cook_time_min,
            "tags": recipe.tags,
            "source_nutrition": (
                json.dumps(extracted.source_nutrition) if extracted.source_nutrition else None
            ),
            "import_method": "jsonld",
        },
    ).one()
    # On a refresh the old children go first; the (recipe_id, position) keys would collide.
    session.execute(delete(RecipeStep).where(RecipeStep.recipe_id == row.id))
    session.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == row.id))
    session.add_all(build_children(row.id, user_id, recipe))
    session.commit()
    return row.id, row.inserted


def import_recipe(
    session: Session,
    redis: Redis,
    fetcher: PageFetcher,
    user_id: int,
    raw_url: str,
    *,
    refresh: bool = False,
) -> ImportResult:
    try:
        source_url = normalize_url(raw_url)
    except UrlError as exc:
        raise ImportFailed(exc.code, exc.message) from None

    existing_id = session.scalar(
        load_sql("find_recipe_by_source_url.sql"), {"source_url": source_url}
    )
    if existing_id is not None and not refresh:
        return ImportResult(get_recipe(session, existing_id), "existing")

    _enforce_rate_limit(redis, user_id)

    # End the transaction before the slow part: a database connection must not be held
    # while we wait for another server (up to the fetch time budget).
    session.commit()
    try:
        page = fetcher.fetch(source_url, refresh=refresh)
    except FetchError as exc:
        raise ImportFailed(exc.code, exc.message) from None

    extracted = extract_recipe(page.body, base_url=page.final_url, source_url=source_url)
    if extracted is None:
        raise ImportFailed(
            "no_recipe_data",
            "No structured recipe data was found on this page. Import of pages without it "
            "is not available yet.",
        )

    recipe_id, inserted = _save(session, user_id, extracted)
    return ImportResult(get_recipe(session, recipe_id), "created" if inserted else "refreshed")
