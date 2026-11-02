from sqlalchemy import text

from app.schemas.ai import AI_UNIT_CODES, AIFullRecipe, AIRefinement


def test_the_units_the_ai_may_use_match_the_units_table(admin_db):
    in_database = set(admin_db.execute(text("SELECT code FROM units")).scalars())

    assert set(AI_UNIT_CODES) == in_database  # a drift here would make the AI invent invalid units


def test_every_field_is_required_so_the_api_must_fill_all_of_them():
    # Structured outputs list all properties as required; optional values are `| None`, so the
    # AI must say "null" explicitly instead of silently skipping a field.
    for model in (AIRefinement, AIFullRecipe):
        schema = model.model_json_schema()
        assert set(schema["required"]) == set(schema["properties"])
    ingredient = AIRefinement.model_json_schema()["$defs"]["AIIngredient"]
    assert set(ingredient["required"]) == set(ingredient["properties"])


def test_full_recipe_extends_the_refinement():
    assert set(AIRefinement.model_fields) < set(AIFullRecipe.model_fields)
