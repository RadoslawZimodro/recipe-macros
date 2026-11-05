"""Food log endpoints. Every endpoint requires a session; state-changing ones also require CSRF."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies import get_current_user, require_csrf
from app.models import User
from app.schemas.food_log import DayOut, DaysOut, FoodLogEntry, FoodLogIn
from app.services import food_log as service

# get_current_user also binds the RLS tenant, so it must run for every route here.
router = APIRouter(
    prefix="/food-log",
    tags=["food log"],
    dependencies=[Depends(get_current_user), Depends(require_csrf)],
)


@router.post("", response_model=FoodLogEntry, status_code=status.HTTP_201_CREATED)
def add_entry(
    payload: FoodLogIn,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> FoodLogEntry:
    """Record servings of a recipe or grams of a product (exactly one of the two)."""
    return service.add_entry(session, user.id, payload)


@router.get("", response_model=DayOut)
def get_day(
    day: Annotated[
        date | None, Query(alias="date", description="Default: today (Polish time)")
    ] = None,
    session: Session = Depends(get_session),
) -> DayOut:
    """The entries of one calendar day, the day's totals and the comparison with the goals."""
    return service.get_day(session, day)


@router.get("/days", response_model=DaysOut)
def get_days(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    session: Session = Depends(get_session),
) -> DaysOut:
    """Totals per day for a range of days (at most 366), empty days included."""
    return service.get_days(session, date_from, date_to)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_id: int, session: Session = Depends(get_session)) -> Response:
    service.delete_entry(session, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
