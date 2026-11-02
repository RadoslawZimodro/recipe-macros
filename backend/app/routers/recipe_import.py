"""POST /recipes/import: import a recipe from a link."""

from fastapi import APIRouter, Depends, HTTPException, Response
from redis import Redis
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.recipe import ImportRequest, RecipeImportOut
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


@router.post("/import", response_model=RecipeImportOut)
def import_from_link(
    payload: ImportRequest,
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    fetcher: PageFetcher = Depends(get_page_fetcher),
) -> RecipeImportOut:
    """Import the recipe at `url` (schema.org JSON-LD).

    201 when a new recipe was saved, 200 when the user already has it (nothing is fetched) or
    when `refresh` re-imported it. Errors carry `{"code": ..., "message": ...}` in `detail`.
    """
    try:
        result = import_recipe(
            session, redis, fetcher, user.id, payload.url, refresh=payload.refresh
        )
    except ImportFailed as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
            headers=headers,
        ) from None

    response.status_code = 201 if result.status == "created" else 200
    return RecipeImportOut(status=result.status, recipe=result.recipe)
