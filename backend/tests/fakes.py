"""Test doubles for the AI: a scripted LLM client and ready-made answers. No network, no cost."""

from app.schemas.ai import AIFullRecipe, AIIngredient, AIRefinement
from app.services.ai_client import AIResponse, AIUsage


class FakeLLM:
    """Stands in for ClaudeClient. Answers (or exceptions) are served in order; the last one
    repeats. Every call is recorded so tests can see what would have been sent to the API."""

    model = "claude-test"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def parse(self, *, system, messages, schema):
        self.calls.append({"system": system, "messages": list(messages), "schema": schema})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return AIResponse(parsed=answer, usage=AIUsage(1200, 400, 0, "req_test"))


def ing(
    line,
    raw="x",
    *,
    qty=None,
    unit=None,
    product=None,
    macros=(100.0, 5.0, 3.0, 15.0),
    optional=False,
    density=None,
    per_unit=None,
):
    """One AIIngredient. `macros` = (kcal, protein, fat, carbs) per 100 g; None for no estimate."""
    kcal, protein, fat, carbs = macros if macros else (None,) * 4
    return AIIngredient(
        line=line,
        raw_text=raw,
        quantity=qty,
        unit=unit,
        product_name=product,
        is_optional=optional,
        kcal_per_100g=kcal,
        protein_per_100g=protein,
        fat_per_100g=fat,
        carbs_per_100g=carbs,
        density_g_per_ml=density,
        grams_per_unit=per_unit,
    )


def full(**overrides) -> AIFullRecipe:
    data = {
        "contains_recipe": True,
        "title": "Zupa",
        "description": None,
        "servings": 4,
        "prep_time_min": None,
        "cook_time_min": None,
        "tags": [],
        "steps": ["Ugotuj."],
        "ingredients": [ing(0, "1 jajko", qty=1, unit="piece", product="jajko")],
    }
    data.update(overrides)
    return AIFullRecipe(**data)


# What a good AI answers for tests/fixtures/recipes/pl_flat.html (7 ingredient lines, 3 steps).
def pl_flat_refinement(**overrides) -> AIRefinement:
    data = {
        "steps": [
            "Zagnieć mąkę, masło, cukier puder i jajko na kruche ciasto. Schłodź w lodówce.",
            "Jabłka obierz, zetrzyj na grubych oczkach i wymieszaj z cynamonem.",
            "Wyłóż ciasto na formę, dodaj jabłka, posyp kruszonką i piecz 60 minut.",
        ],
        "ingredients": [
            ing(0, qty=300, unit="g", product="mąka pszenna", macros=(364, 10.3, 1.0, 76.3)),
            ing(1, qty=200, unit="g", product="masło", macros=(717, 0.9, 81.0, 0.1)),
            ing(2, qty=100, unit="g", product="cukier puder", macros=(400, 0.0, 0.0, 100.0)),
            ing(3, qty=1, unit="piece", product="jajko", macros=(143, 12.6, 9.5, 0.7), per_unit=55),
            ing(4, qty=1, unit="kg", product="jabłko", macros=(52, 0.3, 0.2, 14.0)),
            ing(
                5, qty=2, unit="tbsp", product="cynamon", macros=(247, 4.0, 1.2, 80.0), density=0.56
            ),
            ing(6, qty=1, unit="pinch", product="sól", macros=(0, 0, 0, 0)),
        ],
    }
    data.update(overrides)
    return AIRefinement(**data)
