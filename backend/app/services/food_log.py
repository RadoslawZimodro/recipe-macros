"""The food log: record what was eaten, read a day or a range of days.

Nothing is stored except WHAT was eaten (a recipe and servings, or a product and grams). The macros
come from the food_log_nutrition view on every read, so correcting a recipe line or a product also
corrects the history. The sums per day and the comparison with the goals are SQL
(app/sql/food_log_days.sql); this module only runs the queries and shapes the answer.

A "day" is a calendar day in Polish time, whatever the time zone of the stored timestamps.
"""

from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FoodLog, Recipe
from app.schemas.food_log import (
    DayOut,
    DaysOut,
    DayTotals,
    FoodLogEntry,
    FoodLogIn,
    GoalProgress,
)
from app.schemas.nutrition import Macros
from app.services.nutrition import round_half_up, to_macros
from app.services.sql import load_sql

TIMEZONE = "Europe/Warsaw"
MAX_RANGE_DAYS = 366
# An entry may not lie further in the future than this (clock differences, "tonight's dinner").
MAX_FUTURE = timedelta(days=1)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def today(session: Session) -> date:
    return session.execute(load_sql("current_day.sql"), {"tz": TIMEZONE}).scalar_one()


def _entry(row) -> FoodLogEntry:
    return FoodLogEntry(
        id=row.log_id,
        logged_at=row.logged_at,
        kind="recipe" if row.recipe_id is not None else "product",
        name=row.name,
        recipe_id=row.recipe_id,
        servings=None if row.servings is None else float(row.servings),
        ingredient_id=row.ingredient_id,
        grams=None if row.grams is None else float(row.grams),
        nutrition=None
        if row.kcal is None
        else to_macros(row.kcal, row.protein, row.fat, row.carbs),
        is_estimate=row.is_estimate,
        complete=row.complete,
        lines_total=row.lines_total,
        lines_counted=row.lines_counted,
    )


def _progress(goal, eaten, remaining, percent) -> GoalProgress | None:
    if goal is None:
        return None
    return GoalProgress(
        goal=goal,
        eaten=round_half_up(eaten),
        remaining=round_half_up(remaining),
        percent=float(percent),
    )


def _totals(row) -> DayTotals:
    return DayTotals(
        day=row.day,
        entries=row.entries,
        total=to_macros(row.kcal, row.protein, row.fat, row.carbs),
        is_estimate=row.is_estimate,
        complete=row.complete,
        kcal=_progress(row.kcal_goal, row.kcal, row.kcal_remaining, row.kcal_percent),
        protein=_progress(
            row.protein_goal, row.protein, row.protein_remaining, row.protein_percent
        ),
    )


def _days(session: Session, date_from: date, date_to: date) -> list[DayTotals]:
    rows = session.execute(
        load_sql("food_log_days.sql"),
        {"date_from": date_from, "date_to": date_to, "tz": TIMEZONE},
    )
    return [_totals(row) for row in rows]


def add_entry(session: Session, user_id: int, payload: FoodLogIn) -> FoodLogEntry:
    if payload.logged_at is not None:
        latest = datetime.now(payload.logged_at.tzinfo) + MAX_FUTURE
        if payload.logged_at > latest:
            raise _bad_request("logged_at is too far in the future")

    # A foreign key alone would accept someone else's private recipe or product (FK checks bypass
    # Row-Level Security), so look the id up through RLS first. The policy of the table checks
    # the same again, as the last line of defence.
    if payload.recipe_id is not None:
        found = session.execute(
            select(Recipe.id).where(Recipe.id == payload.recipe_id, Recipe.deleted_at.is_(None))
        ).first()
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    else:
        visible = session.execute(
            load_sql("visible_ingredient_ids.sql"), {"ids": [payload.ingredient_id]}
        ).first()
        if visible is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")

    log = FoodLog(
        user_id=user_id,
        recipe_id=payload.recipe_id,
        servings=payload.servings,
        ingredient_id=payload.ingredient_id,
        grams=payload.grams,
    )
    if payload.logged_at is not None:
        log.logged_at = payload.logged_at
    session.add(log)
    session.flush()
    entry = get_entry(session, log.id)
    session.commit()
    return entry


def get_entry(session: Session, log_id: int) -> FoodLogEntry:
    row = session.execute(
        load_sql("food_log_entries.sql"), {"log_id": log_id, "day": None, "tz": TIMEZONE}
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return _entry(row)


def get_day(session: Session, day: date | None) -> DayOut:
    day = day or today(session)
    entries = session.execute(
        load_sql("food_log_entries.sql"), {"log_id": None, "day": day, "tz": TIMEZONE}
    )
    (totals,) = _days(session, day, day)
    return DayOut(timezone=TIMEZONE, totals=totals, entries=[_entry(r) for r in entries])


def get_days(session: Session, date_from: date, date_to: date) -> DaysOut:
    if date_to < date_from:
        raise _bad_request("'to' must not be before 'from'")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise _bad_request(f"at most {MAX_RANGE_DAYS} days at a time")
    return DaysOut(timezone=TIMEZONE, days=_days(session, date_from, date_to))


def delete_entry(session: Session, log_id: int) -> None:
    deleted = session.execute(
        FoodLog.__table__.delete().where(FoodLog.id == log_id).returning(FoodLog.id)
    ).first()
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    session.commit()


__all__ = ["Macros", "add_entry", "delete_entry", "get_day", "get_days", "get_entry", "today"]
