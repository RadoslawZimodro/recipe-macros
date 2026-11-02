from typing import Literal

from pydantic import BaseModel

# Where a value comes from: off = measured (Open Food Facts), manual = typed in by the user,
# llm_estimate = the AI's guess.
Source = Literal["off", "manual", "llm_estimate"]

PROBLEM_MESSAGES = {
    "no_quantity": "no amount is given (for example 'to taste')",
    "no_unit": "an amount without a unit",
    "no_product": "no product is linked to this line",
    "no_density": "the weight of a spoon or glass of this product is unknown (no density)",
    "no_unit_weight": "the weight of one piece, clove or slice of this product is unknown",
}


class Macros(BaseModel):
    kcal: float
    protein: float
    fat: float
    carbs: float


class Coverage(BaseModel):
    lines_total: int
    lines_counted: int
    # Share of the counted lines that have a known weight and nutrition; null for no lines.
    percent: float | None


class ProductRef(BaseModel):
    id: int
    name: str
    source: Source


class NutritionLine(BaseModel):
    line_id: int
    position: int
    raw_text: str
    optional: bool
    included: bool  # false for optional lines when include_optional is off
    quantity: float | None
    unit: str | None
    product: ProductRef | None
    grams: float | None
    # manual | unit | density | unit_weight | default: how the weight was found
    weight_source: str | None
    # true if the weight basis or the nutrition values are the AI's estimate
    is_estimate: bool | None
    nutrition: Macros | None
    problem: str | None  # machine-readable reason the line could not be computed
    problem_message: str | None


class MissingLine(BaseModel):
    line_id: int
    raw_text: str
    problem: str
    message: str


class NutritionOut(BaseModel):
    recipe_id: int
    servings: int
    # Always true: calories of a recipe are an estimate. The fields below say how good it is.
    is_estimate: Literal[True] = True
    include_optional: bool
    total: Macros
    per_serving: Macros
    coverage: Coverage
    # Share (0-1) of the calories that come from data not estimated by the AI; null if 0 kcal.
    measured_share: float | None
    lines: list[NutritionLine]
    missing: list[MissingLine]
