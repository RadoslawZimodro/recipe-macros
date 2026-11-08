"""Combine the AI's answer with the rest of the recipe into a RecipeIn ready to be saved.

Two cases, matching the two AI modes:
  * structured data present: title, description, servings, times, tags and image stay as the
    page's markup gave them (deterministic); the AI supplies the cleaned steps and the parsed
    ingredient lines. The original ingredient text always comes from the markup, never from the AI;
  * no structured data: everything comes from the AI's reading of the page text.

Step pictures survive the AI by matching text (see match_step_images), not by step count.
"""

import re
from collections import Counter
from decimal import Decimal

from pydantic import ValidationError

from app.schemas.ai import AIFullRecipe, AIIngredient, AIRefinement
from app.schemas.recipe import IngredientLineIn, RecipeIn, StepIn
from app.services.ai_extract import MAX_STEPS, AIInvalidOutput
from app.services.products import COUNT_UNITS, ProductCandidate, normalize_name
from app.services.recipe_extractor import _STEP_NUMBER, ExtractedRecipe

METHOD = "llm"  # stored as import_method: the content was produced with AI's help

# A picture moves to an AI step only when at least this share of the SHORTER text's words is found
# in the other (a merged or split step contains the other, a paraphrase keeps most words).
# 0.7 is deliberately strict: a missing picture is better than one on the wrong step.
MATCH_THRESHOLD = 0.7
TIE_MARGIN = 0.05  # candidates this close to the best are "equally good" (ambiguous)
MIN_WORDS = 3  # shorter texts must match exactly: two shared words prove nothing (see same_count)


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


def _words(text: str) -> Counter[str]:
    return Counter(re.findall(r"\w+", _STEP_NUMBER.sub("", text).lower()))


def _similarity(a: Counter[str], b: Counter[str], min_words: int = MIN_WORDS) -> float:
    if a == b:
        return 1.0 if a else 0.0
    shortest = min(a.total(), b.total())
    if shortest < min_words:
        return 0.0
    return (a & b).total() / shortest


def match_step_images(
    page_steps: list[str], page_images: tuple[str | None, ...], ai_steps: list[str]
) -> tuple[str | None, ...]:
    """Move each page picture to the AI step that holds the same text, or drop it.

    A picture goes to at most one step and each step gets at most one picture. Order is kept
    (no crossing). When the AI merged lines, the first picture wins; when it split a line, the
    first part gets the picture. A tie between steps that are not neighbours is ambiguous: none.
    """
    if not any(page_images):
        return ()
    ai_words = [_words(t) for t in ai_steps]
    result: list[str | None] = [None] * len(ai_steps)
    last = -1
    same_count = len(page_steps) == len(ai_steps)
    for position, (text, image) in enumerate(zip(page_steps, page_images, strict=False)):
        if not image:
            continue
        words = _words(text)
        # With an unchanged step count the same position backs up even a short text.
        scores = [
            _similarity(words, w, 1 if same_count and i == position else MIN_WORDS)
            for i, w in enumerate(ai_words)
        ]
        best = max(scores, default=0.0)
        if best < MATCH_THRESHOLD:
            continue
        close = [i for i, v in enumerate(scores) if v >= best - TIE_MARGIN]
        if close != list(range(close[0], close[-1] + 1)):
            continue  # equally good steps that are not neighbours
        if close[0] > last:  # not after the previous picture's step = merged or crossing
            result[close[0]] = image
            last = close[0]
    return tuple(result) if any(result) else ()


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
    # The AI may merge, split or drop steps: pictures follow the text, not the position.
    images = match_step_images(
        [st.instruction for st in original.steps],
        extracted.step_images,
        [st.instruction for st in recipe.steps],
    )
    return ExtractedRecipe(recipe, extracted.source_nutrition, METHOD, images)


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
