"""Recipe CRUD. Every endpoint requires a session; state-changing ones also require CSRF."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.recipe import RecipeIn, RecipeListOut, RecipeOut
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
