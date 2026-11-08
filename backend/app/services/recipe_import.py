"""Import a recipe from a link: normalize, look up, fetch, read, (AI), save.

Flow: the address is normalized; if the user already has that recipe it is returned as is
(no network). Otherwise the per-user import budget is checked and the page is fetched through the
SSRF-safe fetcher. Then:

  * the page has structured data (JSON-LD / Microdata): the AI takes the ingredient lines apart
    and tidies the steps, the rest comes from the markup;
  * the page has none: the AI reads the page text and fills the whole recipe;
  * the AI is unavailable (no key, no credit, outage, daily limit): a page WITH markup is still
    saved, in its basic form (ingredients as plain text), and the answer says so;
    a page without markup cannot be imported.

The recipe is saved with a single `INSERT ... ON CONFLICT DO UPDATE`
(app/sql/upsert_imported_recipe.sql). AI-made content is stored with import_method = 'llm'.
"""

import json
import logging
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Recipe, RecipeIngredient, RecipeStep
from app.schemas.recipe import RecipeOut
from app.services import ai_merge
from app.services.ai_client import AIUnavailable
from app.services.ai_extract import AIInvalidOutput, NoRecipeOnPage, RecipeAI
from app.services.limits import RateLimitExceeded, check_rate_limit
from app.services.media import StoredImage, delete_images
from app.services.page_fetcher import PageFetcher
from app.services.page_text import page_content
from app.services.products import resolve_products
from app.services.recipe_extractor import ExtractedRecipe, extract_recipe
from app.services.recipes import build_children, get_recipe
from app.services.safe_fetch import FetchedPage, FetchError
from app.services.sql import load_sql
from app.services.step_images import discard, download_cover, download_step_images, new_deadline
from app.services.urls import UrlError, normalize_url

logger = logging.getLogger(__name__)

# HTTP status per error code. 422: this address cannot be imported (the user can pick another);
# 5xx: the other site, the AI service or our infrastructure is the problem and a retry may help.
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
    "ai_invalid_output": 502,
    "timeout": 504,
    "service_unavailable": 503,
    "ai_unavailable": 503,
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
    ai_used: bool = False
    notice: str | None = None  # e.g. "AI unavailable, saved the basic version"


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


def _save(
    session: Session,
    user_id: int,
    extracted: ExtractedRecipe,
    images: dict[int, StoredImage],
    cover: StoredImage | None,
) -> tuple[int, bool, list[str]]:
    """Upsert the recipe row, then replace its steps and ingredient lines. One transaction.
    Also returns the file names of the pictures replaced or dropped (to delete after the commit)."""
    recipe = extracted.recipe
    # The old cover stays when no new one arrived and the photo address is the same; with a
    # different address it would show the wrong picture, so it goes.
    previous = session.execute(
        select(Recipe.image_url, Recipe.cover_path, Recipe.cover_content_type).where(
            Recipe.source_url == recipe.source_url, Recipe.deleted_at.is_(None)
        )  # RLS limits this to the current user
    ).first()
    old_cover = previous.cover_path if previous else None
    if cover is None and old_cover and previous.image_url == recipe.image_url:
        cover = StoredImage(old_cover, previous.cover_content_type)
    row = session.execute(
        load_sql("upsert_imported_recipe.sql"),
        {
            "user_id": user_id,
            "title": recipe.title,
            "description": recipe.description,
            "source_url": recipe.source_url,
            "servings": recipe.servings,
            "image_url": recipe.image_url,
            "cover_path": cover.name if cover else None,
            "cover_content_type": cover.content_type if cover else None,
            "prep_time_min": recipe.prep_time_min,
            "cook_time_min": recipe.cook_time_min,
            "tags": recipe.tags,
            "source_nutrition": (
                json.dumps(extracted.source_nutrition) if extracted.source_nutrition else None
            ),
            "import_method": extracted.method,
        },
    ).one()
    old = session.execute(
        select(
            RecipeStep.position,
            RecipeStep.instruction,
            RecipeStep.image_path,
            RecipeStep.image_content_type,
        ).where(RecipeStep.recipe_id == row.id, RecipeStep.image_path.is_not(None))
    ).all()
    # A step with no new picture (download failed, or the page has none) keeps its old one
    # while its position and text are unchanged; same rule as replace_recipe.
    images = dict(images)
    for pos, instruction, path, content_type in old:
        step = recipe.steps[pos - 1] if pos <= len(recipe.steps) else None
        if pos not in images and step is not None and step.instruction == instruction:
            images[pos] = StoredImage(path, content_type)
    used = {img.name for img in images.values()}
    old_files = [path for _, _, path, _ in old if path not in used]
    if old_cover and (cover is None or cover.name != old_cover):
        old_files.append(old_cover)
    # On a refresh the old children go first; the (recipe_id, position) keys would collide.
    session.execute(delete(RecipeStep).where(RecipeStep.recipe_id == row.id))
    session.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == row.id))
    session.add_all(build_children(row.id, user_id, recipe, images))
    session.commit()
    return row.id, row.inserted, old_files


def _with_ai(
    session: Session,
    ai: RecipeAI,
    user_id: int,
    page: FetchedPage,
    extracted: ExtractedRecipe | None,
    source_url: str,
) -> ExtractedRecipe:
    """The recipe as the AI shapes it. May raise AIUnavailable (the caller can fall back) or
    ImportFailed (the page has no recipe, or the AI gave nothing usable)."""
    try:
        if extracted is not None:
            recipe = extracted.recipe
            result = ai.refine(
                user_id,
                [line.raw_text for line in recipe.ingredients],
                [step.instruction for step in recipe.steps],
            )
            ids = resolve_products(session, user_id, ai_merge.product_candidates(result))
            return ai_merge.merge_refinement(extracted, result, ids)

        content = page_content(
            page.body, base_url=page.final_url, limit=get_settings().ai_max_page_chars
        )
        if content.truncated:
            logger.info("ai_page_text_truncated url=%s", source_url)
        full = ai.extract_page(user_id, content.text, page.final_url)
        ids = resolve_products(session, user_id, ai_merge.product_candidates(full))
        return ai_merge.recipe_from_page(
            full, source_url=source_url, image_url=content.image_url, product_ids=ids
        )
    except NoRecipeOnPage:
        raise ImportFailed("no_recipe_data", "No recipe was found on this page.") from None
    except AIInvalidOutput as exc:
        logger.error("ai_import_failed reason=%s", exc)
        raise ImportFailed(
            "ai_invalid_output",
            "The AI could not turn this page into a usable recipe. Try again later.",
        ) from None


def import_recipe(
    session: Session,
    redis: Redis,
    fetcher: PageFetcher,
    ai: RecipeAI,
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

    # End the transaction before the slow parts: a database connection must not be held while
    # we wait for another server or for the AI.
    session.commit()
    try:
        page = fetcher.fetch(source_url, refresh=refresh)
    except FetchError as exc:
        raise ImportFailed(exc.code, exc.message) from None

    extracted = extract_recipe(page.body, base_url=page.final_url, source_url=source_url)

    notice = None
    ai_used = True
    try:
        final = _with_ai(session, ai, user_id, page, extracted, source_url)
    except AIUnavailable as exc:
        ai_used = False
        if extracted is None:
            if exc.code == "ai_not_configured":
                raise ImportFailed(
                    "no_recipe_data",
                    "No structured recipe data (JSON-LD or Microdata) was found on this page, "
                    f"and AI import is not available: {exc.message}",
                ) from None
            raise ImportFailed(
                "ai_unavailable",
                f"{exc.message} This page has no structured data, so it cannot be imported "
                "without AI.",
            ) from None
        final = extracted
        notice = f"{exc.message} The basic version was saved (ingredients as plain text)."
        logger.warning("ai_unavailable_fallback code=%s", exc.code)

    # Pictures are downloaded without a database transaction open, after the AI has settled
    # the final steps (it may have changed their number; then the pictures are already dropped).
    session.commit()
    deadline = new_deadline()  # one time budget: the cover goes first, the steps get the rest
    cover = download_cover(fetcher, final.recipe.image_url, deadline)
    stored, skipped = download_step_images(fetcher, final.step_images, deadline)
    if extracted is not None:  # pictures the AI's changed step count made unusable
        skipped += sum(1 for u in extracted.step_images if u) - sum(
            1 for u in final.step_images if u
        )
    images = {pos: img for pos, img in enumerate(stored, start=1) if img is not None}
    try:
        recipe_id, inserted, old_files = _save(session, user_id, final, images, cover)
    except Exception:
        session.rollback()
        discard([*stored, cover])  # no orphan files when the save fails
        raise
    delete_images(old_files)  # the refresh replaced them
    if final.recipe.image_url and cover is None:
        note = "The photo of the dish could not be saved."
        notice = f"{notice} {note}" if notice else note
    if skipped:
        note = f"{skipped} step picture(s) could not be saved; those steps have no picture."
        notice = f"{notice} {note}" if notice else note
    return ImportResult(
        get_recipe(session, recipe_id),
        "created" if inserted else "refreshed",
        ai_used=ai_used,
        notice=notice,
    )
