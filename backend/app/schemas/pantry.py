from datetime import datetime

from pydantic import BaseModel


class PantryItemOut(BaseModel):
    ingredient_id: int
    name: str
    added_at: datetime


class StaplesOut(BaseModel):
    # names every user has for free; they cannot be removed
    defaults: list[str]
    own: list[PantryItemOut]


class MissingIngredient(BaseModel):
    line_id: int
    raw_text: str
    # True when the line has no linked product, so it can never be matched with the pantry
    unlinked: bool


class RecipeMatch(BaseModel):
    recipe_id: int
    title: str
    lines_total: int  # required (non-optional) lines
    lines_have: int
    percent: float
    missing: list[MissingIngredient]
