"""Manual corrections: a line's weight and product, and the user's own products."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.seed import conversion, line, product
from tests.test_nutrition import by_position, nutrition, recipe_with
from tests.test_rls import as_tenant

FLOUR = ("mąka pszenna", 364, 10.3, 1.0, 76.3)


@pytest.fixture
def flour(admin_db):
    return product(admin_db, *FLOUR)


def patch_line(client, recipe_id, line_id, **body):
    return client.patch(f"/recipes/{recipe_id}/ingredients/{line_id}", json=body)


def only_line(client, recipe_id):
    return client.get(f"/recipes/{recipe_id}").json()["ingredients"][0]


# --- PATCH /recipes/{id}/ingredients/{line_id} ---
def test_typing_in_a_weight_changes_the_nutrition(alice, flour):
    recipe = recipe_with(alice, [line("1 kopiasta mąki", qty=1, unit="piece", product_id=flour)])
    line_id = only_line(alice, recipe)["id"]
    assert nutrition(alice, recipe)["missing"][0]["problem"] == "no_unit_weight"

    response = patch_line(alice, recipe, line_id, grams=250)

    assert response.status_code == 200
    assert response.json()["ingredients"][0]["grams"] == 250.0
    result = nutrition(alice, recipe)
    assert result["missing"] == []
    assert result["lines"][0]["grams"] == 250 and result["lines"][0]["weight_source"] == "manual"
    assert result["total"]["kcal"] == 910.0  # 364 x 2.5


def test_a_manual_weight_beats_the_computed_one_and_null_removes_it(alice, flour):
    recipe = recipe_with(alice, [line("100 g mąki", qty=100, unit="g", product_id=flour)])
    line_id = only_line(alice, recipe)["id"]

    patch_line(alice, recipe, line_id, grams=50)
    assert nutrition(alice, recipe)["total"]["kcal"] == 182.0  # 364 x 0.5

    patch_line(alice, recipe, line_id, grams=None)  # back to the computed 100 g
    assert nutrition(alice, recipe)["total"]["kcal"] == 364.0
    assert only_line(alice, recipe)["grams"] is None


def test_zero_grams_is_a_valid_weight(alice, flour):
    recipe = recipe_with(alice, [line("mąka", qty=100, unit="g", product_id=flour)])

    patch_line(alice, recipe, only_line(alice, recipe)["id"], grams=0)

    assert nutrition(alice, recipe)["total"]["kcal"] == 0.0


def test_changing_the_product_of_a_line(alice, admin_db, flour):
    rye = product(admin_db, "mąka żytnia", 340, 8, 1.5, 70)
    recipe = recipe_with(alice, [line("100 g mąki", qty=100, unit="g", product_id=flour)])

    response = patch_line(alice, recipe, only_line(alice, recipe)["id"], ingredient_id=rye)

    assert response.json()["ingredients"][0]["ingredient_name"] == "mąka żytnia"
    assert nutrition(alice, recipe)["total"]["kcal"] == 340.0


def test_a_line_can_be_unlinked_from_its_product(alice, flour):
    recipe = recipe_with(alice, [line("100 g mąki", qty=100, unit="g", product_id=flour)])

    response = patch_line(alice, recipe, only_line(alice, recipe)["id"], ingredient_id=None)

    assert response.json()["ingredients"][0]["ingredient_id"] is None
    assert nutrition(alice, recipe)["missing"][0]["problem"] == "no_product"


def test_only_visible_products_can_be_linked(alice, bob, flour):
    secret = bob.post(
        "/ingredients",
        json={
            "canonical_name": "tajne",
            "kcal_per_100g": 1,
            "protein_per_100g": 1,
            "fat_per_100g": 1,
            "carbs_per_100g": 1,
        },
    ).json()["id"]
    recipe = recipe_with(alice, [line("mąka", qty=1, unit="g", product_id=flour)])
    line_id = only_line(alice, recipe)["id"]

    assert patch_line(alice, recipe, line_id, ingredient_id=secret).status_code == 422
    assert patch_line(alice, recipe, line_id, ingredient_id=424242).status_code == 422
    assert only_line(alice, recipe)["ingredient_id"] == flour  # unchanged


@pytest.mark.parametrize(
    "body", [{}, {"grams": -1}, {"grams": "abc"}, {"ingredient_id": 0}, {"user_id": 1}]
)
def test_invalid_line_corrections_are_rejected(alice, flour, body):
    recipe = recipe_with(alice, [line("mąka", qty=1, unit="g", product_id=flour)])

    assert patch_line(alice, recipe, only_line(alice, recipe)["id"], **body).status_code == 422


def test_lines_of_other_users_or_other_recipes_are_not_found(alice, bob, flour):
    mine = recipe_with(alice, [line("mąka", qty=1, unit="g", product_id=flour)])
    other = recipe_with(alice, [line("mąka", qty=1, unit="g", product_id=flour)])
    line_id = only_line(alice, mine)["id"]

    assert patch_line(bob, mine, line_id, grams=1).status_code == 404  # not Bob's recipe
    assert patch_line(alice, other, line_id, grams=1).status_code == 404  # wrong recipe
    assert patch_line(alice, mine, 99999, grams=1).status_code == 404
    alice.delete(f"/recipes/{mine}")
    assert patch_line(alice, mine, line_id, grams=1).status_code == 404  # deleted recipe


def test_line_corrections_need_a_session_and_csrf(client, alice, flour):
    recipe = recipe_with(alice, [line("mąka", qty=1, unit="g", product_id=flour)])
    line_id = only_line(alice, recipe)["id"]

    assert patch_line(client, recipe, line_id, grams=1).status_code == 401
    del alice.headers["X-CSRF-Token"]
    assert patch_line(alice, recipe, line_id, grams=1).status_code == 403


def test_a_manual_weight_survives_when_the_client_sends_the_recipe_back(alice, flour):
    recipe = recipe_with(alice, [line("mąka", qty=1, unit="piece", product_id=flour, grams=80)])
    current = alice.get(f"/recipes/{recipe}").json()
    body = {
        "title": current["title"],
        "ingredients": [
            {
                "raw_text": i["raw_text"],
                "quantity": i["quantity"],
                "unit": i["unit"],
                "ingredient_id": i["ingredient_id"],
                "grams": i["grams"],
            }
            for i in current["ingredients"]
        ],
    }

    assert alice.put(f"/recipes/{recipe}", json=body).status_code == 200

    assert nutrition(alice, recipe)["lines"][0]["grams"] == 80


# --- PATCH /ingredients/{id} ---
def own_product(client, name="cynamon", **overrides):
    body = {
        "canonical_name": name,
        "kcal_per_100g": 247,
        "protein_per_100g": 4,
        "fat_per_100g": 1.2,
        "carbs_per_100g": 80,
    } | overrides
    response = client.post("/ingredients", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_editing_your_own_product_marks_it_as_typed_in(alice, admin_db):
    created = alice.post(
        "/ingredients",
        json={
            "canonical_name": "kasza",
            "kcal_per_100g": 300,
            "protein_per_100g": 10,
            "fat_per_100g": 2,
            "carbs_per_100g": 60,
        },
    ).json()
    admin_db.execute(
        text("UPDATE ingredients SET source = 'llm_estimate' WHERE id = :i"), {"i": created["id"]}
    )
    admin_db.commit()

    response = alice.patch(f"/ingredients/{created['id']}", json={"kcal_per_100g": 350})

    assert response.status_code == 200
    body = response.json()
    assert body["kcal_per_100g"] == 350.0 and body["protein_per_100g"] == 10.0  # others untouched
    assert body["source"] == "manual" and body["is_shared"] is False


def test_a_corrected_product_changes_every_recipe_that_uses_it(alice):
    cinnamon = own_product(alice, density_g_per_ml=0.5)
    recipe = recipe_with(
        alice, [line("20 g cynamonu", qty=20, unit="g", product_id=cinnamon["id"])]
    )
    assert nutrition(alice, recipe)["total"]["kcal"] == 49.4  # 247 x 0.2

    alice.patch(
        f"/ingredients/{cinnamon['id']}",
        json={"kcal_per_100g": 300, "protein_per_100g": 3, "fat_per_100g": 1, "carbs_per_100g": 70},
    )

    assert nutrition(alice, recipe)["total"]["kcal"] == 60.0  # 300 x 0.2


def test_density_can_be_set_and_cleared(alice):
    product_id = own_product(alice)["id"]

    set_ = alice.patch(f"/ingredients/{product_id}", json={"density_g_per_ml": 0.56}).json()
    cleared = alice.patch(f"/ingredients/{product_id}", json={"density_g_per_ml": None}).json()

    assert set_["density_g_per_ml"] == 0.56 and cleared["density_g_per_ml"] is None


def test_renaming_a_product(alice):
    product_id = own_product(alice)["id"]

    assert (
        alice.patch(
            f"/ingredients/{product_id}", json={"canonical_name": "  Cynamon cejloński "}
        ).json()["canonical_name"]
        == "Cynamon cejloński"
    )


def test_a_shared_product_cannot_be_edited_and_the_user_is_told_what_to_do(alice, flour):
    response = alice.patch(f"/ingredients/{flour}", json={"kcal_per_100g": 1})

    assert response.status_code == 403
    assert "your product takes precedence" in response.json()["detail"]


def test_other_users_products_are_not_found(alice, bob):
    secret = own_product(bob)["id"]

    assert alice.patch(f"/ingredients/{secret}", json={"kcal_per_100g": 1}).status_code == 404
    assert alice.patch("/ingredients/99999", json={"kcal_per_100g": 1}).status_code == 404


def test_renaming_into_an_existing_name_conflicts(alice):
    own_product(alice, "cynamon")
    other = own_product(alice, "gałka muszkatołowa")["id"]

    assert (
        alice.patch(f"/ingredients/{other}", json={"canonical_name": "Cynamon"}).status_code == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"kcal_per_100g": -1},
        {"kcal_per_100g": 901},
        {"protein_per_100g": 101},
        {"fat_per_100g": 1.234},
        {"density_g_per_ml": 0},
        {"canonical_name": "   "},
        {"canonical_name": None},
        {"kcal_per_100g": None},
        {"source": "off"},
        {"user_id": 5},
    ],
)
def test_invalid_product_corrections_are_rejected(alice, body):
    product_id = own_product(alice)["id"]

    assert alice.patch(f"/ingredients/{product_id}", json=body).status_code == 422


def test_product_corrections_need_a_session_and_csrf(client, alice):
    product_id = own_product(alice)["id"]

    assert client.patch(f"/ingredients/{product_id}", json={"kcal_per_100g": 1}).status_code == 401
    del alice.headers["X-CSRF-Token"]
    assert alice.patch(f"/ingredients/{product_id}", json={"kcal_per_100g": 1}).status_code == 403


def test_a_user_manual_product_wins_in_the_nutrition_over_the_shared_one(alice, flour):
    recipe = recipe_with(alice, [line("100 g mąki", qty=100, unit="g", product_id=flour)])
    mine = own_product(
        alice,
        "mąka pszenna",
        kcal_per_100g=500,
        protein_per_100g=9,
        fat_per_100g=2,
        carbs_per_100g=80,
    )

    result = by_position(nutrition(alice, recipe))[1]

    assert mine["source"] == "manual" and result["product"]["id"] == mine["id"]
    assert result["nutrition"]["kcal"] == 500.0


# --- the database itself ---
def test_unit_base_amounts(admin_db):
    rows = dict(admin_db.execute(text("SELECT code, base_amount FROM units")).all())

    assert {k: float(v) for k, v in rows.items() if v is not None} == {
        "g": 1, "kg": 1000, "ml": 1, "l": 1000, "tsp": 5, "tbsp": 15, "cup": 250,
    }  # fmt: skip
    assert {k for k, v in rows.items() if v is None} == {"piece", "clove", "slice", "pinch"}


def test_the_database_rejects_a_count_unit_with_a_base_amount_and_vice_versa(admin_db):
    with pytest.raises(DBAPIError, match="ck_units_base_amount"):
        admin_db.execute(text("UPDATE units SET base_amount = 5 WHERE code = 'piece'"))
    admin_db.rollback()
    with pytest.raises(DBAPIError, match="ck_units_base_amount"):
        admin_db.execute(text("UPDATE units SET base_amount = NULL WHERE code = 'g'"))


def test_unit_conversion_constraints(admin_db, flour):
    conversion(admin_db, flour, "piece", 50)
    with pytest.raises(DBAPIError, match="uq_unit_conversions_shared"):
        conversion(admin_db, flour, "piece", 60)  # one shared value per product and unit
    admin_db.rollback()
    with pytest.raises(DBAPIError, match="ck_unit_conversions_grams_positive"):
        conversion(admin_db, flour, "clove", 0)
    admin_db.rollback()
    with pytest.raises(DBAPIError, match="uq_unit_conversions_general"):
        admin_db.execute(
            text(
                "INSERT INTO unit_conversions (unit_code, grams_per_unit, source) "
                "VALUES ('pinch', 1, 'manual')"
            )
        )


def test_users_may_write_only_their_own_conversions(alice, bob, flour):
    insert = text(
        "INSERT INTO unit_conversions (ingredient_id, user_id, unit_code, grams_per_unit, source) "
        "VALUES (:i, :u, 'piece', 50, 'manual')"
    )
    with as_tenant(alice.user_id) as conn:
        conn.execute(insert, {"i": flour, "u": alice.user_id})  # her own: allowed
    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(alice.user_id) as conn:
        conn.execute(insert, {"i": flour, "u": None})  # a shared one: refused
    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(alice.user_id) as conn:
        conn.execute(insert, {"i": flour, "u": bob.user_id})  # on behalf of Bob: refused
    with as_tenant(bob.user_id) as conn:
        seen = conn.execute(
            text("SELECT count(*) FROM unit_conversions WHERE ingredient_id = :i"), {"i": flour}
        ).scalar_one()
    assert seen == 0  # Alice's conversion is invisible to Bob
