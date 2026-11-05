from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.nutrition import Macros

MAX_SERVINGS = 100
MAX_GRAMS = 10000


class FoodLogIn(BaseModel):
    """Exactly one of: servings of a recipe (recipe_id + servings) or grams of a product
    (ingredient_id + grams)."""

    recipe_id: int | None = None
    servings: float | None = Field(None, gt=0, le=MAX_SERVINGS)
    ingredient_id: int | None = None
    grams: float | None = Field(None, gt=0, le=MAX_GRAMS)
    # When it was eaten; must carry a time zone (e.g. 2026-03-10T23:30:00+01:00). Default: now.
    logged_at: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> "FoodLogIn":
        recipe_kind = self.recipe_id is not None and self.servings is not None
        product_kind = self.ingredient_id is not None and self.grams is not None
        has_recipe_part = self.recipe_id is not None or self.servings is not None
        has_product_part = self.ingredient_id is not None or self.grams is not None
        if (
            recipe_kind == product_kind
            or (recipe_kind and has_product_part)
            or (product_kind and has_recipe_part)
        ):
            raise ValueError(
                "give either recipe_id with servings, or ingredient_id with grams (not both)"
            )
        if self.logged_at is not None and self.logged_at.tzinfo is None:
            raise ValueError("logged_at needs a time zone, e.g. 2026-03-10T23:30:00+01:00")
        return self


class FoodLogEntry(BaseModel):
    id: int
    logged_at: datetime
    kind: Literal["recipe", "product"]
    name: str
    recipe_id: int | None
    servings: float | None
    ingredient_id: int | None
    grams: float | None
    # null when nothing could be computed (a recipe with no usable ingredient lines)
    nutrition: Macros | None
    # True when part of the value is an AI guess; every value is an estimate anyway
    is_estimate: bool
    # False when some ingredient lines of the recipe could not be computed (see its nutrition)
    complete: bool
    lines_total: int | None
    lines_counted: int | None


class GoalProgress(BaseModel):
    goal: int
    eaten: float
    remaining: float  # negative when the goal is exceeded
    percent: float


class DayTotals(BaseModel):
    day: date
    entries: int
    total: Macros
    is_estimate: bool
    complete: bool
    kcal: GoalProgress | None  # null when no goal is set
    protein: GoalProgress | None


class DayOut(BaseModel):
    timezone: str
    totals: DayTotals
    entries: list[FoodLogEntry]


class DaysOut(BaseModel):
    timezone: str
    days: list[DayTotals]
