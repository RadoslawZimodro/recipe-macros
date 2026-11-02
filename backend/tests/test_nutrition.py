"""Macronutrients of a recipe. Every expected number below is worked out by hand in the comments,
so the tests check the ARITHMETIC, not just that something is returned."""

import pytest
from sqlalchemy import text

from tests.seed import conversion, line, product
from tests.test_recipes import create
from tests.test_rls import as_tenant, count


def nutrition(client, recipe_id, **params):
    response = client.get(f"/recipes/{recipe_id}/nutrition", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def recipe_with(client, lines, **overrides):
    return create(client, ingredients=lines, **overrides)["id"]


def by_position(result):
    return {item["position"]: item for item in result["lines"]}


@pytest.fixture
def catalog(admin_db):
    """Shared products per 100 g, with the conversions they need."""
    ids = {
        "flour": product(admin_db, "mąka pszenna", 364, 10.3, 1.0, 76.3, density=0.53),
        "honey": product(admin_db, "miód", 304, 0.3, 0, 82.4, density=1.42),
        "egg": product(admin_db, "jajko", 143, 12.6, 9.5, 0.7),
        "salt": product(admin_db, "sól", 0, 0, 0, 0),
        "butter": product(admin_db, "masło", 717, 0.9, 81, 0.1),
        "milk": product(admin_db, "mleko", 64, 3.3, 3.6, 4.8),  # no density known
    }
    conversion(admin_db, ids["egg"], "piece", 55)
    return ids


@pytest.fixture
def main_recipe(alice, catalog):
    ids = catalog
    return recipe_with(
        alice,
        [
            line("300 g mąki", qty=300, unit="g", product_id=ids["flour"]),  # 1
            line("2 łyżki miodu", qty=2, unit="tbsp", product_id=ids["honey"]),  # 2
            line("2 jajka", qty=2, unit="piece", product_id=ids["egg"]),  # 3
            line("szczypta soli", qty=1, unit="pinch", product_id=ids["salt"]),  # 4
            line("sól do smaku", product_id=ids["salt"]),  # 5: no amount
            line("1 łyżeczka cynamonu", qty=1, unit="tsp"),  # 6: no product
            line("1 szklanka mleka", qty=1, unit="cup", product_id=ids["milk"]),  # 7: no density
            line("1 kostka masła", qty=1, unit="piece", product_id=ids["butter"], grams=250),  # 8
            line(
                "łyżka miodu do polania", qty=1, unit="tbsp", product_id=ids["honey"], optional=True
            ),
        ],
        servings=4,
    )


# --- the arithmetic ---
def test_each_line_gets_the_right_weight_and_nutrition(alice, main_recipe):
    lines = by_position(nutrition(alice, main_recipe))

    # 1. 300 g flour: 300 g; kcal 364 x 3 = 1092, protein 10.3 x 3 = 30.9, fat 3, carbs 228.9
    assert lines[1]["grams"] == 300 and lines[1]["weight_source"] == "unit"
    assert lines[1]["nutrition"] == {"kcal": 1092.0, "protein": 30.9, "fat": 3.0, "carbs": 228.9}
    # 2. 2 tbsp honey: 2 x 15 ml x 1.42 g/ml = 42.6 g; kcal 304 x 0.426 = 129.504
    assert lines[2]["grams"] == 42.6 and lines[2]["weight_source"] == "density"
    assert lines[2]["nutrition"] == {"kcal": 129.5, "protein": 0.1, "fat": 0.0, "carbs": 35.1}
    # 3. 2 eggs: 2 x 55 g = 110 g; kcal 143 x 1.1 = 157.3, protein 13.86, fat 10.45, carbs 0.77
    assert lines[3]["grams"] == 110 and lines[3]["weight_source"] == "unit_weight"
    assert lines[3]["nutrition"] == {"kcal": 157.3, "protein": 13.9, "fat": 10.5, "carbs": 0.8}
    # 4. a pinch of salt: the general default of 0.5 g, and salt has no calories
    assert lines[4]["grams"] == 0.5 and lines[4]["weight_source"] == "default"
    assert lines[4]["nutrition"]["kcal"] == 0.0
    # 8. 250 g typed in by the user beats "1 piece" (butter has no piece weight at all)
    assert lines[8]["grams"] == 250 and lines[8]["weight_source"] == "manual"
    assert lines[8]["nutrition"] == {"kcal": 1792.5, "protein": 2.3, "fat": 202.5, "carbs": 0.3}


def test_totals_and_per_serving(alice, main_recipe):
    result = nutrition(alice, main_recipe)

    # kcal 1092 + 129.504 + 157.3 + 0 + 1792.5 = 3171.304
    # protein 30.9 + 0.1278 + 13.86 + 0 + 2.25 = 47.1378
    # fat 3 + 0 + 10.45 + 0 + 202.5 = 215.95
    # carbs 228.9 + 35.1024 + 0.77 + 0 + 0.25 = 265.0224
    total = result["total"]
    assert total["kcal"] == pytest.approx(3171.3, abs=0.05)
    assert total["protein"] == pytest.approx(47.1, abs=0.05)
    assert total["fat"] == pytest.approx(215.95, abs=0.06)
    assert total["carbs"] == pytest.approx(265.0, abs=0.05)
    # 4 servings: 3171.304 / 4 = 792.826, 47.1378 / 4 = 11.78,
    # 215.95 / 4 = 53.99, 265.0224 / 4 = 66.26
    per = result["per_serving"]
    assert per["kcal"] == pytest.approx(792.8, abs=0.05) and per["protein"] == pytest.approx(
        11.8, abs=0.05
    )
    assert per["fat"] == pytest.approx(54.0, abs=0.06) and per["carbs"] == pytest.approx(
        66.3, abs=0.05
    )
    assert result["servings"] == 4 and result["is_estimate"] is True


def test_lines_that_cannot_be_computed_are_listed_with_a_reason(alice, main_recipe):
    result = nutrition(alice, main_recipe)

    reasons = {m["raw_text"]: m["problem"] for m in result["missing"]}
    assert reasons == {
        "sól do smaku": "no_quantity",
        "1 łyżeczka cynamonu": "no_product",
        "1 szklanka mleka": "no_density",
    }
    assert all(m["message"] for m in result["missing"])
    lines = by_position(result)
    assert lines[5]["nutrition"] is None and lines[5]["grams"] is None
    assert lines[6]["product"] is None and lines[6]["problem"] == "no_product"
    assert lines[7]["problem_message"].startswith("the weight of a spoon or glass")


def test_coverage_counts_the_lines_that_were_computed(alice, main_recipe):
    coverage = nutrition(alice, main_recipe)["coverage"]

    # 8 counted lines (the optional one is left out); 5 of them have grams and nutrition
    assert coverage == {"lines_total": 8, "lines_counted": 5, "percent": 62.5}


def test_optional_lines_are_counted_only_on_request(alice, main_recipe):
    without = nutrition(alice, main_recipe)
    with_optional = nutrition(alice, main_recipe, include_optional=True)

    optional = by_position(without)[9]
    assert optional["included"] is False and optional["nutrition"]["kcal"] == 64.8  # still shown
    assert without["include_optional"] is False and with_optional["include_optional"] is True
    # 1 tbsp honey = 15 x 1.42 = 21.3 g -> 304 x 0.213 = 64.752 kcal more
    assert with_optional["total"]["kcal"] == pytest.approx(
        without["total"]["kcal"] + 64.752, abs=0.06
    )
    assert with_optional["coverage"] == {"lines_total": 9, "lines_counted": 6, "percent": 66.7}


def test_measured_share_is_one_when_nothing_is_an_ai_guess(alice, main_recipe):
    assert nutrition(alice, main_recipe)["measured_share"] == 1.0


# --- units ---
@pytest.mark.parametrize(
    ("quantity", "unit", "grams"),
    [
        (500, "g", 500),
        (0.5, "kg", 500),  # 0.5 x 1000
        (250, "ml", 132.5),  # 250 ml x 0.53 g/ml
        (1, "l", 530),  # 1000 ml x 0.53
        (3, "tsp", 7.95),  # 3 x 5 ml x 0.53
        (2, "tbsp", 15.9),  # 2 x 15 ml x 0.53
        (1, "cup", 132.5),  # a glass/cup is 250 ml: 250 x 0.53
    ],
)
def test_every_unit_converts_with_its_base_amount(alice, catalog, quantity, unit, grams):
    recipe = recipe_with(
        alice, [line("mąka", qty=quantity, unit=unit, product_id=catalog["flour"])]
    )

    result = by_position(nutrition(alice, recipe))[1]

    assert result["grams"] == pytest.approx(grams, abs=0.06)
    assert result["nutrition"]["kcal"] == pytest.approx(364 * grams / 100, abs=0.06)


def test_an_amount_without_a_unit_cannot_be_weighed(alice, catalog):
    recipe = recipe_with(alice, [line("3 jajka", qty=3, product_id=catalog["egg"])])

    result = nutrition(alice, recipe)

    assert result["missing"][0]["problem"] == "no_unit"


def test_a_count_unit_without_a_known_weight_is_missing_not_guessed(alice, catalog):
    recipe = recipe_with(
        alice, [line("2 plastry masła", qty=2, unit="slice", product_id=catalog["butter"])]
    )

    problem = nutrition(alice, recipe)["missing"][0]["problem"]

    assert problem == "no_unit_weight"


def test_servings_rounding(alice, catalog):
    recipe = recipe_with(
        alice, [line("100 g mąki", qty=100, unit="g", product_id=catalog["flour"])], servings=3
    )

    result = nutrition(alice, recipe)

    assert result["total"]["kcal"] == 364.0
    assert result["per_serving"]["kcal"] == 121.3  # 364 / 3 = 121.33


def test_recipe_without_ingredients(alice):
    recipe = recipe_with(alice, [])

    result = nutrition(alice, recipe)

    assert result["total"] == {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    assert result["coverage"] == {"lines_total": 0, "lines_counted": 0, "percent": None}
    assert result["measured_share"] is None and result["lines"] == [] and result["missing"] == []


# --- how sure are we: estimates are reported, never hidden ---
def test_ai_estimated_nutrition_lowers_the_measured_share(alice, admin_db, catalog):
    cinnamon = product(
        admin_db,
        "cynamon",
        247,
        4,
        1.2,
        80,
        density=0.56,
        user_id=alice.user_id,
        source="llm_estimate",
    )
    recipe = recipe_with(
        alice,
        [
            line("100 g mąki", qty=100, unit="g", product_id=catalog["flour"]),
            line("1 łyżeczka cynamonu", qty=1, unit="tsp", product_id=cinnamon),
        ],
    )

    result = nutrition(alice, recipe)

    # cinnamon: 1 tsp = 5 ml x 0.56 = 2.8 g -> 247 x 0.028 = 6.916 kcal; flour 364 kcal is measured
    lines = by_position(result)
    assert lines[2]["is_estimate"] is True and lines[2]["product"]["source"] == "llm_estimate"
    assert lines[1]["is_estimate"] is False
    assert result["measured_share"] == pytest.approx(364 / (364 + 6.916), abs=0.001)  # 0.981


def test_an_ai_estimated_weight_makes_the_line_an_estimate_even_for_measured_nutrition(
    alice, admin_db, catalog
):
    cucumber = product(admin_db, "ogórek", 15, 0.7, 0.1, 3.6)
    conversion(admin_db, cucumber, "piece", 150, user_id=alice.user_id, source="llm_estimate")
    recipe = recipe_with(alice, [line("2 ogórki", qty=2, unit="piece", product_id=cucumber)])

    result = nutrition(alice, recipe)

    only = result["lines"][0]
    assert only["grams"] == 300 and only["product"]["source"] == "off"
    assert only["is_estimate"] is True  # the nutrition is measured, the weight is a guess
    assert result["measured_share"] == 0.0


def test_the_response_is_always_flagged_as_an_estimate(alice, catalog):
    recipe = recipe_with(
        alice, [line("100 g mąki", qty=100, unit="g", product_id=catalog["flour"])]
    )

    assert nutrition(alice, recipe)["is_estimate"] is True


# --- which product and which conversion wins ---
def test_a_measured_shared_product_replaces_an_old_ai_estimate_of_the_same_name(alice, admin_db):
    estimate = product(
        admin_db, "ryż", 800, 0, 0, 0, user_id=alice.user_id, source="llm_estimate"
    )  # a bad old guess
    recipe = recipe_with(alice, [line("100 g ryżu", qty=100, unit="g", product_id=estimate)])
    before = by_position(nutrition(alice, recipe))[1]
    assert before["product"]["source"] == "llm_estimate" and before["nutrition"]["kcal"] == 800.0

    product(admin_db, "ryż", 350, 7, 0.6, 78)  # the shared catalog now has measured rice

    after = by_position(nutrition(alice, recipe))[1]
    assert after["product"]["source"] == "off" and after["nutrition"]["kcal"] == 350.0
    assert after["is_estimate"] is False  # the recipe improved without being touched


def test_the_users_own_manual_product_beats_the_shared_one(alice, admin_db):
    shared = product(admin_db, "mąka żytnia", 340, 8, 1.5, 70)
    product(admin_db, "mąka żytnia", 500, 9, 2, 80, user_id=alice.user_id, source="manual")
    recipe = recipe_with(alice, [line("100 g mąki", qty=100, unit="g", product_id=shared)])

    result = by_position(nutrition(alice, recipe))[1]

    assert result["product"]["source"] == "manual" and result["nutrition"]["kcal"] == 500.0


def test_other_users_products_never_take_part(alice, bob, admin_db):
    shared = product(admin_db, "kasza", 350, 12, 3, 70)
    product(admin_db, "kasza", 1, 0, 0, 0, user_id=bob.user_id, source="manual")  # Bob's own
    recipe = recipe_with(alice, [line("100 g kaszy", qty=100, unit="g", product_id=shared)])

    assert by_position(nutrition(alice, recipe))[1]["nutrition"]["kcal"] == 350.0


def test_the_users_own_conversion_beats_the_shared_one(alice, bob, admin_db, catalog):
    conversion(admin_db, catalog["egg"], "piece", 70, user_id=alice.user_id)  # Alice's large eggs
    recipes = {
        "alice": recipe_with(
            alice, [line("1 jajko", qty=1, unit="piece", product_id=catalog["egg"])]
        ),
        "bob": recipe_with(bob, [line("1 jajko", qty=1, unit="piece", product_id=catalog["egg"])]),
    }

    assert nutrition(alice, recipes["alice"])["lines"][0]["grams"] == 70  # her own value
    assert nutrition(bob, recipes["bob"])["lines"][0]["grams"] == 55  # the shared one


def test_density_can_come_from_a_users_ml_conversion(alice, admin_db, catalog):
    conversion(admin_db, catalog["milk"], "ml", 1.03, user_id=alice.user_id, source="llm_estimate")
    recipe = recipe_with(
        alice, [line("1 szklanka mleka", qty=1, unit="cup", product_id=catalog["milk"])]
    )

    result = nutrition(alice, recipe)

    only = result["lines"][0]
    assert only["grams"] == pytest.approx(257.5, abs=0.06)  # 250 ml x 1.03
    assert only["weight_source"] == "density" and only["is_estimate"] is True
    assert result["missing"] == []


def test_a_product_specific_conversion_beats_the_general_default(alice, admin_db, catalog):
    conversion(admin_db, catalog["salt"], "pinch", 0.36)
    recipe = recipe_with(
        alice, [line("szczypta soli", qty=1, unit="pinch", product_id=catalog["salt"])]
    )

    only = nutrition(alice, recipe)["lines"][0]

    assert only["grams"] == 0.4 and only["weight_source"] == "unit_weight"  # 0.36 -> 0.4


# --- the endpoint ---
def test_the_endpoint_needs_a_session(client, alice, main_recipe):
    assert client.get(f"/recipes/{main_recipe}/nutrition").status_code == 401


def test_other_users_recipes_and_deleted_recipes_are_not_found(alice, bob, main_recipe):
    assert bob.get(f"/recipes/{main_recipe}/nutrition").status_code == 404
    alice.delete(f"/recipes/{main_recipe}")
    assert alice.get(f"/recipes/{main_recipe}/nutrition").status_code == 404
    assert alice.get("/recipes/99999/nutrition").status_code == 404


# --- the view, tested as the restricted role ---
def test_the_view_runs_with_the_callers_rights(alice, bob, main_recipe, admin_db):
    options = admin_db.execute(
        text("SELECT reloptions FROM pg_class WHERE relname = 'recipe_line_nutrition'")
    ).scalar_one()
    assert "security_invoker=true" in options  # without it the view would run as its owner

    with as_tenant(None) as conn:
        assert count(conn, "recipe_line_nutrition") == 0
    with as_tenant(bob.user_id) as conn:
        assert count(conn, "recipe_line_nutrition") == 0  # Bob sees nothing of Alice's recipe
    with as_tenant(alice.user_id) as conn:
        assert count(conn, "recipe_line_nutrition") == 9
    assert admin_db.execute(text("SELECT count(*) FROM recipe_line_nutrition")).scalar_one() == 9
