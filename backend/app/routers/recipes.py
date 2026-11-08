"""Recipe CRUD. Every endpoint requires a session; state-changing ones also require CSRF."""

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.nutrition import NutritionOut
from app.schemas.recipe import LinePatch, RecipeIn, RecipeListOut, RecipeOut
from app.services import nutrition as nutrition_service
from app.services import recipes as recipe_service

# get_current_user also binds the RLS tenant, so it must run for every route here.
router = APIRouter(
    prefix="/recipes",
    tags=["recipes"],
    dependencies=[Depends(get_current_user), Depends(require_csrf)],
)


@router.post("", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(
    payload: RecipeIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RecipeOut:
    recipe_id = recipe_service.create_recipe(session, user.id, payload)
    return recipe_service.get_recipe(session, recipe_id)


@router.get("", response_model=RecipeListOut)
def list_recipes(
    q: str | None = Query(None, max_length=100, description="Search in the title"),
    tag: str | None = Query(None, max_length=50, description="Exact tag"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> RecipeListOut:
    q = q.strip() if q else None
    tag = tag.strip().lower() if tag else None
    return recipe_service.list_recipes(
        session, q=q or None, tag=tag or None, limit=limit, offset=offset
    )


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: int, session: Session = Depends(get_session)) -> RecipeOut:
    return recipe_service.get_recipe(session, recipe_id)


@router.get("/{recipe_id}/nutrition", response_model=NutritionOut)
def get_nutrition(
    recipe_id: int,
    include_optional: bool = Query(False, description="Count optional ingredient lines too"),
    session: Session = Depends(get_session),
) -> NutritionOut:
    """Macronutrients of the recipe: total and per serving, always flagged as an estimate, with
    the coverage, the share backed by non-AI data, and the source of every line."""
    return nutrition_service.get_nutrition(session, recipe_id, include_optional=include_optional)


def _image_response(path: Path, content_type: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
            # Belt and braces: if the file is ever opened directly, nothing in it can run.
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/{recipe_id}/cover", response_class=FileResponse)
def get_cover(
    recipe_id: int = PathParam(ge=1, le=2_147_483_647),  # int4: larger ids would be a DB error
    session: Session = Depends(get_session),
) -> FileResponse:
    """The saved photo of the dish (a local copy made at import). 404 if the recipe is not
    yours or has none. Private cache only: the picture is behind the login."""
    return _image_response(*recipe_service.get_cover(session, recipe_id))


@router.get("/{recipe_id}/steps/{position}/image", response_class=FileResponse)
def get_step_image(
    recipe_id: int = PathParam(ge=1, le=2_147_483_647),
    position: int = PathParam(ge=1, le=10_000),
    session: Session = Depends(get_session),
) -> FileResponse:
    """The saved picture of a step (a local copy made at import). Same rules as the cover."""
    return _image_response(*recipe_service.get_step_image(session, recipe_id, position))


@router.patch("/{recipe_id}/ingredients/{line_id}", response_model=RecipeOut)
def patch_ingredient_line(
    recipe_id: int, line_id: int, patch: LinePatch, session: Session = Depends(get_session)
) -> RecipeOut:
    """Correct one ingredient line: type in its weight in grams and/or change its product."""
    recipe_service.patch_line(session, recipe_id, line_id, patch)
    return recipe_service.get_recipe(session, recipe_id)


@router.put("/{recipe_id}", response_model=RecipeOut)
def replace_recipe(
    recipe_id: int, payload: RecipeIn, session: Session = Depends(get_session)
) -> RecipeOut:
    recipe_service.replace_recipe(session, recipe_id, payload)
    return recipe_service.get_recipe(session, recipe_id)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(recipe_id: int, session: Session = Depends(get_session)) -> Response:
    recipe_service.delete_recipe(session, recipe_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
