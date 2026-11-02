"""Combine the AI's answer with the rest of the recipe into a RecipeIn ready to be saved.

Two cases, matching the two AI modes:
  * structured data present: title, description, servings, times, tags and image stay as the
    page's markup gave them (deterministic); the AI supplies the cleaned steps and the parsed
    ingredient lines. The original ingredient text always comes from the markup, never from the AI;
  * no structured data: everything comes from the AI's reading of the page text.
"""

from decimal import Decimal

from pydantic import ValidationError

from app.schemas.ai import AIFullRecipe, AIIngredient, AIRefinement
from app.schemas.recipe import IngredientLineIn, RecipeIn, StepIn
from app.services.ai_extract import MAX_STEPS, AIInvalidOutput
from app.services.products import COUNT_UNITS, ProductCandidate, normalize_name
from app.services.recipe_extractor import ExtractedRecipe

METHOD = "llm"  # stored as import_method: the content was produced with AI's help


def product_candidates(ai: AIRefinement) -> list[ProductCandidate]:
    return [
        ProductCandidate(
            name=item.product_name,
            kcal=item.kcal_per_100g,
            protein=item.protein_per_100g,
            fat=item.fat_per_100g,
            carbs=item.carbs_per_100g,
            density=item.density_g_per_ml,
            unit_weights=(
                ((item.unit, item.grams_per_unit),)
                if item.unit in COUNT_UNITS and item.grams_per_unit
                else ()
            ),
        )
        for item in ai.ingredients
        if item.product_name
    ]


def _lines(
    items: list[AIIngredient], raw_texts: list[str] | None, product_ids: dict[str, int]
) -> list[IngredientLineIn]:
    lines = []
    for item in sorted(items, key=lambda i: i.line):
        raw = raw_texts[item.line] if raw_texts is not None else item.raw_text
        name = normalize_name(item.product_name)
        lines.append(
            IngredientLineIn(
                raw_text=raw.strip()[:500],
                quantity=None if item.quantity is None else Decimal(str(round(item.quantity, 3))),
                unit=item.unit,
                ingredient_id=product_ids.get(name) if name else None,
                is_optional=item.is_optional,
            )
        )
    return lines


def _steps(steps: list[str]) -> list[StepIn]:
    return [StepIn(instruction=s.strip()[:5000]) for s in steps if s.strip()][:MAX_STEPS]


def merge_refinement(
    extracted: ExtractedRecipe, ai: AIRefinement, product_ids: dict[str, int]
) -> ExtractedRecipe:
    original = extracted.recipe
    try:
        recipe = original.model_copy(
            update={
                "steps": _steps(ai.steps),
                "ingredients": _lines(
                    ai.ingredients, [i.raw_text for i in original.ingredients], product_ids
                ),
            }
        )
        RecipeIn.model_validate(recipe.model_dump())
    except (ValidationError, IndexError) as exc:
        raise AIInvalidOutput(f"the merged recipe is not valid: {exc}") from None
    return ExtractedRecipe(recipe, extracted.source_nutrition, METHOD)


def recipe_from_page(
    ai: AIFullRecipe, *, source_url: str, image_url: str | None, product_ids: dict[str, int]
) -> ExtractedRecipe:
    tags = [t.strip().lower() for t in ai.tags if t.strip() and len(t.strip()) <= 50]
    try:
        recipe = RecipeIn(
            title=(ai.title or "").strip()[:300],
            description=(ai.description or "").strip()[:5000] or None,
            source_url=source_url,
            image_url=image_url,
            servings=max(1, min(ai.servings or 1, 1000)),
            prep_time_min=_minutes(ai.prep_time_min),
            cook_time_min=_minutes(ai.cook_time_min),
            tags=list(dict.fromkeys(tags))[:8],
            steps=_steps(ai.steps),
            ingredients=_lines(ai.ingredients, None, product_ids),
        )
    except ValidationError as exc:
        raise AIInvalidOutput(f"the recipe is not valid: {exc}") from None
    return ExtractedRecipe(recipe, None, METHOD)


def _minutes(value: int | None) -> int | None:
    return value if value is not None and 0 < value <= 100_000 else None
