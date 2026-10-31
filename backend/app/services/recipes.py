"""Recipe use cases. Writes go through the ORM; reads are the SQL files in app/sql.

Every function runs inside the caller's request session, which already has the RLS tenant
bound (get_current_user), so queries only ever see the current user's rows.
"""

from fastapi import HTTPException, status
from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Recipe, RecipeIngredient, RecipeStep
from app.schemas.recipe import RecipeIn, RecipeListOut, RecipeOut, RecipeSummary
from app.services.sql import like_pattern, load_sql

_SOURCE_URL_INDEX = "uq_recipes_user_source_url"


def _not_found() -> HTTPException:
    # 404 (not 403) for other users' recipes too: their existence is not revealed.
    return HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")


def _validate_references(session: Session, payload: RecipeIn) -> None:
    """Reject unknown unit codes and ingredient ids the user cannot see (422)."""
    unit_codes = sorted({line.unit for line in payload.ingredients if line.unit})
    if unit_codes:
        known = set(session.scalars(load_sql("existing_unit_codes.sql"), {"codes": unit_codes}))
        if unknown := [code for code in unit_codes if code not in known]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown unit(s): {', '.join(unknown)}"
            )

    ingredient_ids = sorted(
        {line.ingredient_id for line in payload.ingredients if line.ingredient_id}
    )
    if ingredient_ids:
        visible = set(
            session.scalars(load_sql("visible_ingredient_ids.sql"), {"ids": ingredient_ids})
        )
        if unknown_ids := [i for i in ingredient_ids if i not in visible]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Unknown ingredient id(s): {', '.join(map(str, unknown_ids))}",
            )


def _scalar_fields(payload: RecipeIn) -> dict:
    return payload.model_dump(exclude={"steps", "ingredients"})


def _children(
    recipe_id: int, user_id: int, payload: RecipeIn
) -> list[RecipeStep | RecipeIngredient]:
    """Build step and ingredient rows; list order becomes `position` (1-based)."""
    steps = [
        RecipeStep(recipe_id=recipe_id, user_id=user_id, position=pos, instruction=step.instruction)
        for pos, step in enumerate(payload.steps, start=1)
    ]
    lines = [
        RecipeIngredient(
            recipe_id=recipe_id,
            user_id=user_id,
            position=pos,
            ingredient_id=line.ingredient_id,
            raw_text=line.raw_text,
            quantity=line.quantity,
            unit_code=line.unit,
            is_optional=line.is_optional,
        )
        for pos, line in enumerate(payload.ingredients, start=1)
    ]
    return [*steps, *lines]


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(exc.orig.diag, "constraint_name", None) == _SOURCE_URL_INDEX:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "You already have a recipe from this source URL"
            ) from None
        raise


def create_recipe(session: Session, user_id: int, payload: RecipeIn) -> int:
    _validate_references(session, payload)
    recipe = Recipe(user_id=user_id, **_scalar_fields(payload))
    session.add(recipe)
    try:
        session.flush()  # assigns recipe.id; also surfaces a duplicate source_url early
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a recipe from this source URL"
        ) from None
    session.add_all(_children(recipe.id, user_id, payload))
    _commit(session)
    return recipe.id


def replace_recipe(session: Session, recipe_id: int, payload: RecipeIn) -> None:
    """PUT semantics: the body is the new state, steps and lines are replaced as a whole."""
    recipe = session.get(Recipe, recipe_id)  # RLS hides other users' rows
    if recipe is None or recipe.deleted_at is not None:
        raise _not_found()
    _validate_references(session, payload)

    for field, value in _scalar_fields(payload).items():
        setattr(recipe, field, value)
    # Delete first (executed immediately), then insert: the (recipe_id, position) keys of
    # the new rows would otherwise collide with the old ones at flush time.
    session.execute(delete(RecipeStep).where(RecipeStep.recipe_id == recipe_id))
    session.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id))
    session.add_all(_children(recipe_id, recipe.user_id, payload))
    _commit(session)


def delete_recipe(session: Session, recipe_id: int) -> None:
    """Soft delete: the row stays (food log history keeps working), it just disappears."""
    result = session.execute(
        update(Recipe)
        .where(Recipe.id == recipe_id, Recipe.deleted_at.is_(None))
        .values(deleted_at=func.now())
        .returning(Recipe.id)
        .execution_options(synchronize_session=False)
    )
    if result.first() is None:
        raise _not_found()
    session.commit()


def get_recipe(session: Session, recipe_id: int) -> RecipeOut:
    row = session.execute(load_sql("get_recipe.sql"), {"recipe_id": recipe_id}).mappings().first()
    if row is None:
        raise _not_found()
    return RecipeOut.model_validate(dict(row))


def list_recipes(
    session: Session, *, q: str | None, tag: str | None, limit: int, offset: int
) -> RecipeListOut:
    filters = {"q": q, "pattern": like_pattern(q), "tag": tag}
    rows = (
        session.execute(load_sql("list_recipes.sql"), {**filters, "limit": limit, "offset": offset})
        .mappings()
        .all()
    )
    total = session.scalar(load_sql("count_recipes.sql"), filters)
    return RecipeListOut(
        items=[RecipeSummary.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
