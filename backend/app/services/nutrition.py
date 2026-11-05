"""Macronutrients of a recipe. The arithmetic lives in SQL (the recipe_line_nutrition view and
app/sql/recipe_nutrition.sql); this module only reads the rows and shapes the answer.

The numbers are ESTIMATES and the answer says how good they are: what share of the lines could
be computed (coverage), what share of the calories rests on data that is not an AI guess
(measured_share), and for every line where its weight and nutrition came from.
"""

from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.nutrition import (
    PROBLEM_MESSAGES,
    Coverage,
    Macros,
    MissingLine,
    NutritionLine,
    NutritionOut,
    ProductRef,
)
from app.services.sql import load_sql


def round_half_up(value) -> float:
    """One decimal, rounding .x5 UP like a nutrition label (Python's round() would turn 2.25 into
    2.2). Going through Decimal avoids binary floating-point surprises."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def to_macros(kcal, protein, fat, carbs) -> Macros:
    return Macros(
        kcal=round_half_up(kcal),
        protein=round_half_up(protein),
        fat=round_half_up(fat),
        carbs=round_half_up(carbs),
    )


def get_nutrition(session: Session, recipe_id: int, *, include_optional: bool) -> NutritionOut:
    head = (
        session.execute(
            load_sql("recipe_nutrition.sql"),
            {"recipe_id": recipe_id, "include_optional": include_optional},
        )
        .mappings()
        .first()
    )
    if head is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    rows = (
        session.execute(load_sql("recipe_nutrition_lines.sql"), {"recipe_id": recipe_id})
        .mappings()
        .all()
    )

    lines: list[NutritionLine] = []
    missing: list[MissingLine] = []
    for row in rows:
        included = include_optional or not row["is_optional"]
        problem = row["problem"]
        computed = row["kcal"] is not None
        lines.append(
            NutritionLine(
                line_id=row["line_id"],
                position=row["position"],
                raw_text=row["raw_text"],
                optional=row["is_optional"],
                included=included,
                quantity=None if row["quantity"] is None else float(row["quantity"]),
                unit=row["unit_code"],
                product=None
                if row["product_id"] is None
                else ProductRef(
                    id=row["product_id"], name=row["product_name"], source=row["macro_source"]
                ),
                grams=None if row["grams"] is None else round_half_up(row["grams"]),
                weight_source=row["weight_source"],
                is_estimate=row["is_estimate"] if computed else None,
                nutrition=to_macros(row["kcal"], row["protein"], row["fat"], row["carbs"])
                if computed
                else None,
                problem=problem,
                problem_message=PROBLEM_MESSAGES.get(problem) if problem else None,
            )
        )
        if included and problem:
            missing.append(
                MissingLine(
                    line_id=row["line_id"],
                    raw_text=row["raw_text"],
                    problem=problem,
                    message=PROBLEM_MESSAGES[problem],
                )
            )

    total = to_macros(head["kcal"], head["protein"], head["fat"], head["carbs"])
    servings = head["servings"]
    per_serving = to_macros(
        float(head["kcal"]) / servings,
        float(head["protein"]) / servings,
        float(head["fat"]) / servings,
        float(head["carbs"]) / servings,
    )
    lines_total, lines_counted = head["lines_total"], head["lines_counted"]
    kcal = float(head["kcal"])
    return NutritionOut(
        recipe_id=head["recipe_id"],
        servings=servings,
        include_optional=include_optional,
        total=total,
        per_serving=per_serving,
        coverage=Coverage(
            lines_total=lines_total,
            lines_counted=lines_counted,
            percent=round(100 * lines_counted / lines_total, 1) if lines_total else None,
        ),
        measured_share=round(float(head["kcal_measured"]) / kcal, 3) if kcal > 0 else None,
        lines=lines,
        missing=missing,
    )
