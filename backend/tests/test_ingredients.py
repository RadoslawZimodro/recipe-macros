"""Product catalog (shared + private) and the units dictionary."""

import pytest
from sqlalchemy import text

from tests.test_recipes import create, recipe_payload

FLOUR = {
    "canonical_name": "Mąka pszenna",
    "kcal_per_100g": 364,
    "protein_per_100g": 10.3,
    "fat_per_100g": 1,
    "carbs_per_100g": 76.3,
}


def add_shared(admin_db, name="Cukier", kcal=400):
    """Insert a shared catalog product (user_id NULL) the way a migration or script would."""
    admin_db.execute(
        text(
            "INSERT INTO ingredients (user_id, canonical_name, kcal_per_100g, protein_per_100g, "
            "fat_per_100g, carbs_per_100g, source) VALUES (NULL, :n, :k, 0, 0, 100, 'off')"
        ),
        {"n": name, "k": kcal},
    )
    admin_db.commit()


def names(client, **params):
    return [i["canonical_name"] for i in client.get("/ingredients", params=params).json()["items"]]


# --- creating private products ---
def test_create_private_product(alice):
    response = alice.post("/ingredients", json=FLOUR)

    assert response.status_code == 201
    body = response.json()
    assert body["canonical_name"] == "Mąka pszenna"
    assert body["kcal_per_100g"] == 364.0 and body["protein_per_100g"] == 10.3
    assert body["source"] == "manual"
    assert body["is_shared"] is False
    assert names(alice) == ["Mąka pszenna"]


def test_product_names_are_unique_per_user_case_insensitively(alice, bob):
    assert alice.post("/ingredients", json=FLOUR).status_code == 201

    duplicate = {**FLOUR, "canonical_name": "mąka PSZENNA"}
    assert alice.post("/ingredients", json=duplicate).status_code == 409
    assert bob.post("/ingredients", json=FLOUR).status_code == 201


@pytest.mark.parametrize(
    "overrides",
    [
        {"canonical_name": "  "},
        {"kcal_per_100g": -1},
        {"kcal_per_100g": 901},
        {"protein_per_100g": 100.5},
        {"fat_per_100g": 1.234},
        {"density_g_per_ml": 0},
        {"user_id": None},  # the owner is never taken from the body
        {"source": "off"},  # nor is the source: hand-entered values are always 'manual'
    ],
)
def test_invalid_product_is_rejected(alice, overrides):
    assert alice.post("/ingredients", json={**FLOUR, **overrides}).status_code == 422


def test_creating_a_product_requires_session_and_csrf(client, alice):
    assert client.post("/ingredients", json=FLOUR).status_code == 401
    del alice.headers["X-CSRF-Token"]
    assert alice.post("/ingredients", json=FLOUR).status_code == 403


# --- visibility: shared + own, never somebody else's ---
def test_shared_catalog_is_visible_to_everyone_and_marked_shared(alice, bob, admin_db):
    add_shared(admin_db, "Cukier")

    for client in (alice, bob):
        item = client.get("/ingredients").json()["items"][0]
        assert item["canonical_name"] == "Cukier"
        assert item["is_shared"] is True
        assert item["source"] == "off"


def test_private_products_are_invisible_to_other_users(alice, bob, admin_db):
    add_shared(admin_db, "Cukier")
    alice.post("/ingredients", json=FLOUR)

    assert set(names(alice)) == {"Cukier", "Mąka pszenna"}
    assert names(bob) == ["Cukier"]


def test_a_private_product_may_share_a_name_with_a_shared_one(alice, admin_db):
    add_shared(admin_db, "Mąka pszenna")

    assert alice.post("/ingredients", json=FLOUR).status_code == 201
    assert names(alice) == ["Mąka pszenna", "Mąka pszenna"]


# --- search ---
def test_search_by_substring_and_pagination(alice, admin_db):
    for name in ("Mąka pszenna", "Mąka żytnia", "Masło", "Mleko 2%"):
        add_shared(admin_db, name)

    assert set(names(alice, q="mąka")) == {"Mąka pszenna", "Mąka żytnia"}
    assert names(alice, q="mleko 2%") == ["Mleko 2%"]  # '%' is literal, not a wildcard

    page = alice.get("/ingredients", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2


def test_search_tolerates_typos(alice, admin_db):
    add_shared(admin_db, "Cukier puder")

    assert names(alice, q="cukir puder") == ["Cukier puder"]


# --- recipe lines referencing products ---
def test_recipe_line_shows_the_linked_product_name(alice):
    product = alice.post("/ingredients", json=FLOUR).json()

    recipe = create(
        alice,
        ingredients=[
            {"raw_text": "200 g mąki", "quantity": 200, "unit": "g", "ingredient_id": product["id"]}
        ],
    )

    line = recipe["ingredients"][0]
    assert line["ingredient_id"] == product["id"]
    assert line["ingredient_name"] == "Mąka pszenna"


def test_recipe_can_reference_a_shared_product(alice, admin_db):
    add_shared(admin_db, "Cukier")
    shared_id = alice.get("/ingredients").json()["items"][0]["id"]

    recipe = create(alice, ingredients=[{"raw_text": "cukier", "ingredient_id": shared_id}])

    assert recipe["ingredients"][0]["ingredient_name"] == "Cukier"


def test_recipe_cannot_reference_another_users_private_product(alice, bob):
    secret = alice.post("/ingredients", json=FLOUR).json()

    response = bob.post(
        "/recipes",
        json=recipe_payload(ingredients=[{"raw_text": "mąka", "ingredient_id": secret["id"]}]),
    )

    assert response.status_code == 422
    assert str(secret["id"]) in response.json()["detail"]


def test_recipe_cannot_reference_a_missing_product(alice):
    response = alice.post(
        "/recipes", json=recipe_payload(ingredients=[{"raw_text": "x", "ingredient_id": 424242}])
    )

    assert response.status_code == 422


# --- units ---
def test_units_dictionary(alice):
    codes = {u["code"]: u["kind"] for u in alice.get("/units").json()}

    assert codes["g"] == "mass" and codes["ml"] == "volume" and codes["clove"] == "count"
    assert {"tsp", "tbsp", "cup", "pinch", "piece"} <= set(codes)


def test_units_require_a_session(client):
    assert client.get("/units").status_code == 401
