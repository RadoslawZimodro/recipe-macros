"""The pantry ("fridge"), the always-at-home list and matching recipes with what the user has.

The matching is one SQL query (app/sql/pantry_match.sql); this module checks product ids, runs the
queries and shapes the answers.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.pantry import DefaultStaple, PantryItem, StapleIngredient
from app.schemas.pantry import MissingIngredient, PantryItemOut, RecipeMatch, StaplesOut
from app.services.sql import load_sql

_TABLES = {"pantry": PantryItem, "staples": StapleIngredient}


def _items(session: Session, which: str, ingredient_id: int | None = None) -> list[PantryItemOut]:
    rows = session.execute(
        load_sql("pantry_list.sql"), {"list": which, "ingredient_id": ingredient_id}
    )
    return [
        PantryItemOut(ingredient_id=r.ingredient_id, name=r.name, added_at=r.added_at) for r in rows
    ]


def list_items(session: Session, which: str) -> list[PantryItemOut]:
    return _items(session, which)


def list_staples(session: Session) -> StaplesOut:
    defaults = session.scalars(select(DefaultStaple.name).order_by(DefaultStaple.name)).all()
    return StaplesOut(defaults=list(defaults), own=_items(session, "staples"))


def add_item(session: Session, user_id: int, which: str, ingredient_id: int) -> PantryItemOut:
    """Idempotent: adding a product that is already there changes nothing."""
    # A foreign key alone would accept someone else's private product (FK checks bypass RLS), so
    # look the id up through RLS first; the table's policy checks the same again.
    visible = session.execute(
        load_sql("visible_ingredient_ids.sql"), {"ids": [ingredient_id]}
    ).first()
    if visible is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    table = _TABLES[which]
    session.execute(
        insert(table)
        .values(user_id=user_id, ingredient_id=ingredient_id)
        .on_conflict_do_nothing(index_elements=["user_id", "ingredient_id"])
    )
    (item,) = _items(session, which, ingredient_id)
    session.commit()
    return item


def remove_item(session: Session, which: str, ingredient_id: int) -> None:
    table = _TABLES[which]
    deleted = session.execute(
        table.__table__.delete().where(table.ingredient_id == ingredient_id).returning(table.id)
    ).first()
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product is not on the list")
    session.commit()


def match_recipes(session: Session, *, min_percent: float, limit: int) -> list[RecipeMatch]:
    rows = session.execute(
        load_sql("pantry_match.sql"), {"min_percent": min_percent, "limit": limit}
    )
    return [
        RecipeMatch(
            recipe_id=r.recipe_id,
            title=r.title,
            lines_total=r.lines_total,
            lines_have=r.lines_have,
            percent=float(r.percent),
            missing=[MissingIngredient(**m) for m in r.missing],
        )
        for r in rows
    ]
