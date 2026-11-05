"""Pantry endpoints. Every endpoint requires a session; state-changing ones also require CSRF."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.pantry import PantryItemOut, RecipeMatch, StaplesOut
from app.services import pantry as service

# get_current_user also binds the RLS tenant, so it must run for every route here.
_PROTECTED = [Depends(get_current_user), Depends(require_csrf)]

router = APIRouter(prefix="/pantry", tags=["pantry"], dependencies=_PROTECTED)
staples_router = APIRouter(prefix="/staples", tags=["pantry"], dependencies=_PROTECTED)


@router.get("", response_model=list[PantryItemOut])
def list_pantry(session: Session = Depends(get_session)) -> list[PantryItemOut]:
    """The products the user has now."""
    return service.list_items(session, "pantry")


# Declared before "/{ingredient_id}" so the path "recipes" is never read as a product id.
@router.get("/recipes", response_model=list[RecipeMatch])
def matching_recipes(
    min_percent: Annotated[float, Query(ge=0, le=100)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = Depends(get_session),
) -> list[RecipeMatch]:
    """Recipes sorted by the share of their required ingredients the user has, with what is
    missing. Staples (default and own) count as available; optional lines are left out."""
    return service.match_recipes(session, min_percent=min_percent, limit=limit)


@router.put("/{ingredient_id}", response_model=PantryItemOut)
def add_to_pantry(
    ingredient_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PantryItemOut:
    """Put a product in the pantry (idempotent)."""
    return service.add_item(session, user.id, "pantry", ingredient_id)


@router.delete("/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_pantry(ingredient_id: int, session: Session = Depends(get_session)) -> Response:
    service.remove_item(session, "pantry", ingredient_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@staples_router.get("", response_model=StaplesOut)
def list_staples(session: Session = Depends(get_session)) -> StaplesOut:
    """The default always-at-home names plus the user's own."""
    return service.list_staples(session)


@staples_router.put("/{ingredient_id}", response_model=PantryItemOut)
def add_staple(
    ingredient_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PantryItemOut:
    """Mark a product as always at home (idempotent)."""
    return service.add_item(session, user.id, "staples", ingredient_id)


@staples_router.delete("/{ingredient_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_staple(ingredient_id: int, session: Session = Depends(get_session)) -> Response:
    service.remove_item(session, "staples", ingredient_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
