"""Product catalog (shared + the user's private products) and the units dictionary."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import Ingredient, User
from app.schemas.ingredient import (
    IngredientIn,
    IngredientListOut,
    IngredientOut,
    IngredientPatch,
    UnitOut,
)
from app.services.sql import like_pattern, load_sql

router = APIRouter(
    prefix="/ingredients",
    tags=["ingredients"],
    dependencies=[Depends(get_current_user), Depends(require_csrf)],
)
units_router = APIRouter(
    prefix="/units", tags=["ingredients"], dependencies=[Depends(get_current_user)]
)


def _out(ingredient: Ingredient) -> IngredientOut:
    return IngredientOut(
        **{c: getattr(ingredient, c) for c in IngredientOut.model_fields if c != "is_shared"},
        is_shared=ingredient.user_id is None,
    )


@router.get("", response_model=IngredientListOut)
def search_ingredients(
    q: str | None = Query(None, max_length=100, description="Search in the product name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> IngredientListOut:
    q = (q.strip() if q else None) or None
    filters = {"q": q, "pattern": like_pattern(q)}
    rows = (
        session.execute(
            load_sql("search_ingredients.sql"), {**filters, "limit": limit, "offset": offset}
        )
        .mappings()
        .all()
    )
    total = session.scalar(load_sql("count_ingredients.sql"), filters)
    return IngredientListOut(
        items=[IngredientOut.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=IngredientOut, status_code=status.HTTP_201_CREATED)
def create_ingredient(
    payload: IngredientIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IngredientOut:
    """Add a private product. The shared catalog cannot be changed through the API."""
    # Values entered by hand are an estimate by the user: source is always 'manual'.
    ingredient = Ingredient(user_id=user.id, source="manual", **payload.model_dump())
    session.add(ingredient)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a product with this name"
        ) from None
    return _out(ingredient)


@router.patch("/{ingredient_id}", response_model=IngredientOut)
def update_ingredient(
    ingredient_id: int, patch: IngredientPatch, session: Session = Depends(get_session)
) -> IngredientOut:
    """Correct one of your own products. Shared products cannot be changed."""
    ingredient = session.get(Ingredient, ingredient_id)  # Row-Level Security: shared + own
    if ingredient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if ingredient.user_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Shared products cannot be edited. Add your own product with the same name: "
            "your product takes precedence over the shared one.",
        )

    for name in patch.model_fields_set:
        setattr(ingredient, name, getattr(patch, name))
    ingredient.source = "manual"
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a product with this name"
        ) from None
    return _out(ingredient)


@units_router.get("", response_model=list[UnitOut])
def list_units(session: Session = Depends(get_session)) -> list[UnitOut]:
    rows = session.execute(load_sql("list_units.sql")).mappings().all()
    return [UnitOut.model_validate(dict(row)) for row in rows]
