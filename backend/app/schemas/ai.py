"""What the AI is asked to return. These models are also the JSON schema sent to the API
(structured outputs), so the reply is guaranteed to fit the shape; the MEANING of the values is
checked afterwards by app.services.ai_extract.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Mirrors the `units` dictionary table (migration 0004); test_ai_schema.py fails if they drift.
UnitCode = Literal["g", "kg", "ml", "l", "tsp", "tbsp", "cup", "piece", "clove", "slice", "pinch"]
AI_UNIT_CODES: tuple[str, ...] = UnitCode.__args__  # type: ignore[attr-defined]


class AIIngredient(BaseModel):
    """One ingredient line, taken apart."""

    line: int = Field(description="0-based number of the ingredient line this entry describes")
    raw_text: str = Field(
        description="the ingredient line, copied exactly as written in the source"
    )
    quantity: float | None = Field(
        description="numeric amount (1/2 -> 0.5, '2-3' -> 2); null if there is none ('to taste')"
    )
    unit: UnitCode | None = Field(description="unit from the allowed list, null if none fits")
    product_name: str | None = Field(
        description="the food itself: singular, lower case, no amounts, in the language of the "
        "line (e.g. 'mąka pszenna', 'oliwa z oliwek', 'egg'); null if the line is not a food"
    )
    is_optional: bool = Field(description="true if the line says the ingredient is optional")
    kcal_per_100g: float | None = Field(description="estimated kcal per 100 g of the product")
    protein_per_100g: float | None = Field(description="estimated protein g per 100 g")
    fat_per_100g: float | None = Field(description="estimated fat g per 100 g")
    carbs_per_100g: float | None = Field(description="estimated carbohydrates g per 100 g")


class AIRefinement(BaseModel):
    """Used when the page already has structured data: only steps and ingredients are returned."""

    steps: list[str] = Field(description="the real preparation steps, in order, source wording")
    ingredients: list[AIIngredient]


class AIFullRecipe(AIRefinement):
    """Used when the page has no structured data: the whole recipe is read from the page text."""

    contains_recipe: bool = Field(description="false if the page text does not contain a recipe")
    title: str | None
    description: str | None = Field(description="one or two sentences, or null")
    servings: int | None
    prep_time_min: int | None
    cook_time_min: int | None
    tags: list[str] = Field(description="up to 8 short lower-case tags (course, cuisine, diet)")
