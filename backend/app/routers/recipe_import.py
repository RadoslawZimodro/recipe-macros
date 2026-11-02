"""POST /recipes/import: import a recipe from a link."""

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Response
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.recipe import ImportRequest, RecipeImportOut
from app.services.ai_client import ClaudeClient
from app.services.ai_extract import RecipeAI
from app.services.page_cache import PageCache
from app.services.page_fetcher import PageFetcher
from app.services.recipe_import import ImportFailed, import_recipe
from app.services.redis_client import get_redis

router = APIRouter(
    prefix="/recipes",
    tags=["import"],
    dependencies=[Depends(get_current_user), Depends(require_csrf)],
)


def get_page_fetcher(redis: Redis = Depends(get_redis)) -> PageFetcher:
    """The production fetcher (Redis page cache). Tests replace this dependency."""
    return PageFetcher(PageCache(redis))


@lru_cache
def _claude_client(
    api_key: str, model: str, timeout: float, max_output_tokens: int
) -> ClaudeClient:
    return ClaudeClient(api_key, model, timeout=timeout, max_output_tokens=max_output_tokens)


def get_recipe_ai(redis: Redis = Depends(get_redis)) -> RecipeAI:
    """The AI helper; without an API key it still works as "AI not available". Tests replace it."""
    settings = get_settings()
    client = None
    if settings.anthropic_api_key:
        client = _claude_client(
            settings.anthropic_api_key,
            settings.ai_model,
            settings.ai_timeout_sec,
            settings.ai_max_output_tokens,
        )
    return RecipeAI(client, redis)


@router.post("/import", response_model=RecipeImportOut)
def import_from_link(
    payload: ImportRequest,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    fetcher: PageFetcher = Depends(get_page_fetcher),
    ai: RecipeAI = Depends(get_recipe_ai),
) -> RecipeImportOut:
    """Import the recipe at `url` (schema.org JSON-LD).

    201 when a new recipe was saved, 200 when the user already has it (nothing is fetched) or
    when `refresh` re-imported it. Errors carry `{"code": ..., "message": ...}` in `detail`.
    """
    try:
        result = import_recipe(
            session, redis, fetcher, ai, user.id, payload.url, refresh=payload.refresh
        )
    except ImportFailed as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
            headers=headers,
        ) from None

    response.status_code = 201 if result.status == "created" else 200
    return RecipeImportOut(
        status=result.status, recipe=result.recipe, ai_used=result.ai_used, notice=result.notice
    )
