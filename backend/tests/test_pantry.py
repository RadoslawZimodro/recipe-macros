"""The pantry: what the user has, the always-at-home lists and matching recipes with them.
The expected percentages are worked out by hand in the comments."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.main import app
from tests.seed import line, product
from tests.test_recipes import create
from tests.test_rls import as_tenant


@pytest.fixture
def catalog(admin_db):
    names = ["mąka pszenna", "jajko", "mleko", "masło", "cukier", "sól"]
    return {name: product(admin_db, name, 100, 1, 1, 10) for name in names}


def recipe(client, catalog, title, names, optional=()):
    lines = [line(f"1 {n}", qty=1, unit="piece", product_id=catalog[n]) for n in names]
    lines += [
        line(f"1 {n} (opcja)", qty=1, unit="piece", product_id=catalog[n], optional=True)
        for n in optional
    ]
    return create(client, title=title, ingredients=lines)


@pytest.fixture
def recipes(alice, catalog):
    """Four recipes of alice (required lines in brackets)."""
    return {
        "pancakes": recipe(
            alice, catalog, "Naleśniki", ["mąka pszenna", "jajko", "mleko", "sól"], ["masło"]
        ),
        "fritters": recipe(alice, catalog, "Placki", ["mąka pszenna", "masło", "cukier", "jajko"]),
        "mystery": create(
            alice,
            title="Tajemnica",
            ingredients=[
                line("1 mleko", qty=1, unit="piece", product_id=catalog["mleko"]),
                line("szczypta czegoś"),  # no linked product
            ],
        ),
        "only_optional": create(
            alice, title="Dodatki", ingredients=[line("bazylia", optional=True)]
        ),
    }


def stock(client, catalog, *names, which="pantry"):
    for name in names:
        response = client.put(f"/{which}/{catalog[name]}")
        assert response.status_code == 200, response.text


def match(client, **params):
    response = client.get("/pantry/recipes", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(matches):
    return [m["title"] for m in matches]


# --- the lists ---
def test_a_product_can_be_added_listed_and_removed(alice, catalog):
    added = alice.put(f"/pantry/{catalog['mleko']}")

    assert added.status_code == 200 and added.json()["name"] == "mleko"
    assert [i["name"] for i in alice.get("/pantry").json()] == ["mleko"]
    assert alice.delete(f"/pantry/{catalog['mleko']}").status_code == 204
    assert alice.get("/pantry").json() == []
    assert alice.delete(f"/pantry/{catalog['mleko']}").status_code == 404


def test_adding_twice_changes_nothing(alice, catalog):
    first = alice.put(f"/pantry/{catalog['jajko']}").json()
    second = alice.put(f"/pantry/{catalog['jajko']}").json()

    assert first == second and len(alice.get("/pantry").json()) == 1


def test_the_list_is_sorted_by_name(alice, catalog):
    stock(alice, catalog, "mleko", "cukier", "jajko")

    assert [i["name"] for i in alice.get("/pantry").json()] == ["cukier", "jajko", "mleko"]


def test_an_unknown_product_is_not_found(alice):
    assert alice.put("/pantry/999").status_code == 404
    assert alice.put("/staples/999").status_code == 404


def test_the_staples_come_with_defaults_and_the_users_own(alice, catalog):
    stock(alice, catalog, "cukier", which="staples")

    staples = alice.get("/staples").json()

    assert set(staples["defaults"]) == {"woda", "sól", "pieprz"}
    assert [i["name"] for i in staples["own"]] == ["cukier"]
    assert alice.delete(f"/staples/{catalog['cukier']}").status_code == 204
    assert alice.get("/staples").json()["own"] == []


def test_the_pantry_and_the_staples_are_separate_lists(alice, catalog):
    stock(alice, catalog, "mleko")
    stock(alice, catalog, "cukier", which="staples")

    assert [i["name"] for i in alice.get("/pantry").json()] == ["mleko"]
    assert [i["name"] for i in alice.get("/staples").json()["own"]] == ["cukier"]


# --- the matching ---
def test_recipes_are_sorted_by_the_share_of_ingredients_the_user_has(alice, catalog, recipes):
    stock(alice, catalog, "mąka pszenna", "jajko", "mleko")

    result = match(alice)

    # Naleśniki: flour, egg, milk in the pantry and salt by default = 4 of 4 = 100%
    # Placki: flour and egg of (flour, butter, sugar, egg) = 2 of 4 = 50%, butter and sugar missing
    # Tajemnica: milk of (milk, an unlinked line) = 1 of 2 = 50%, the unlinked one is missing
    # equal percentages: the recipe that lacks fewer ingredients comes first
    assert titles(result) == ["Naleśniki", "Tajemnica", "Placki"]
    assert [m["percent"] for m in result] == [100.0, 50.0, 50.0]
    assert [(m["lines_have"], m["lines_total"]) for m in result] == [(4, 4), (1, 2), (2, 4)]
    assert result[0]["missing"] == []
    assert [x["raw_text"] for x in result[2]["missing"]] == ["1 masło", "1 cukier"]


def test_a_line_without_a_product_counts_as_missing_and_is_marked(alice, catalog, recipes):
    stock(alice, catalog, "mleko")

    mystery = next(m for m in match(alice) if m["title"] == "Tajemnica")

    assert mystery["percent"] == 50.0
    assert mystery["missing"] == [
        {
            "line_id": mystery["missing"][0]["line_id"],
            "raw_text": "szczypta czegoś",
            "unlinked": True,
        }
    ]


def test_optional_lines_are_left_out_and_a_recipe_with_only_optional_lines_is_not_listed(
    alice, catalog, recipes
):
    stock(alice, catalog, "mąka pszenna", "jajko", "mleko")

    result = match(alice)

    pancakes = next(m for m in result if m["title"] == "Naleśniki")
    assert pancakes["lines_total"] == 4  # the optional butter is not counted
    assert "Dodatki" not in titles(result)


def test_the_default_staples_count_without_being_added(alice, catalog, recipes):
    result = match(alice)  # an empty pantry

    # only the salt of Naleśniki (1 of 4 = 25%) is available by default
    pancakes = next(m for m in result if m["title"] == "Naleśniki")
    assert pancakes["percent"] == 25.0 and pancakes["lines_have"] == 1


def test_the_users_own_staples_count_as_available(alice, catalog, recipes):
    stock(alice, catalog, "mąka pszenna", "jajko")
    before = next(m for m in match(alice) if m["title"] == "Placki")
    stock(alice, catalog, "cukier", which="staples")

    after = next(m for m in match(alice) if m["title"] == "Placki")

    assert before["percent"] == 50.0
    # flour, egg and sugar of (flour, butter, sugar, egg) = 3 of 4
    assert after["percent"] == 75.0 and [x["raw_text"] for x in after["missing"]] == ["1 masło"]


def test_the_percentage_is_rounded_to_one_decimal(alice, catalog):
    recipe(alice, catalog, "Trzy", ["mąka pszenna", "jajko", "cukier"])
    stock(alice, catalog, "mąka pszenna", "jajko")

    assert match(alice)[0]["percent"] == 66.7  # 2 of 3


def test_products_are_matched_by_name_not_by_id(alice, admin_db, catalog):
    recipe(alice, catalog, "Chleb", ["mąka pszenna"])
    own = product(admin_db, "Mąka Pszenna", 340, 10, 1, 70, user_id=alice.user_id)

    alice.put(f"/pantry/{own}")  # the user's own flour, not the catalog's

    assert match(alice)[0]["percent"] == 100.0


def test_filters_and_limit(alice, catalog, recipes):
    stock(alice, catalog, "mąka pszenna", "jajko", "mleko")

    assert titles(match(alice, min_percent=100)) == ["Naleśniki"]
    assert titles(match(alice, min_percent=60)) == ["Naleśniki"]
    assert len(match(alice, limit=2)) == 2


@pytest.mark.parametrize(
    "params", [{"min_percent": -1}, {"min_percent": 101}, {"limit": 0}, {"limit": 101}]
)
def test_unreasonable_parameters_are_refused(alice, params):
    assert alice.get("/pantry/recipes", params=params).status_code == 422


def test_deleted_recipes_are_not_suggested(alice, catalog, recipes):
    alice.delete(f"/recipes/{recipes['pancakes']['id']}")

    assert "Naleśniki" not in titles(match(alice))


def test_there_is_nothing_to_suggest_without_recipes(alice):
    assert match(alice) == []


# --- isolation and access ---
def test_users_see_neither_the_lists_nor_the_recipes_of_others(alice, bob, catalog, recipes):
    stock(alice, catalog, "mąka pszenna", "jajko", "mleko")
    stock(alice, catalog, "cukier", which="staples")

    assert bob.get("/pantry").json() == []
    assert bob.get("/staples").json()["own"] == []
    assert match(bob) == []  # bob has no recipes of his own
    assert bob.delete(f"/pantry/{catalog['mleko']}").status_code == 404


def test_someone_elses_private_product_cannot_be_added(alice, bob, admin_db):
    private = product(admin_db, "mój sos", 100, 1, 1, 20, user_id=alice.user_id)

    assert bob.put(f"/pantry/{private}").status_code == 404
    assert bob.put(f"/staples/{private}").status_code == 404


def test_the_endpoints_need_a_session_and_the_csrf_header(alice, catalog):
    anonymous = TestClient(app)
    for method, url in [
        ("get", "/pantry"),
        ("get", "/pantry/recipes"),
        ("put", "/pantry/1"),
        ("delete", "/pantry/1"),
        ("get", "/staples"),
        ("put", "/staples/1"),
        ("delete", "/staples/1"),
    ]:
        assert getattr(anonymous, method)(url).status_code == 401, (method, url)

    alice.headers.pop("X-CSRF-Token")
    assert alice.put(f"/pantry/{catalog['mleko']}").status_code == 403


# --- the database enforces the rules itself ---
def test_the_same_product_cannot_be_on_a_list_twice(admin_db, alice, catalog):
    insert = text("INSERT INTO pantry_items (user_id, ingredient_id) VALUES (:u, :i)")
    admin_db.execute(insert, {"u": alice.user_id, "i": catalog["mleko"]})
    admin_db.commit()

    with pytest.raises(IntegrityError, match="uq_pantry_items_user_id_ingredient_id"):
        admin_db.execute(insert, {"u": alice.user_id, "i": catalog["mleko"]})
    admin_db.rollback()


@pytest.mark.parametrize("table", ["pantry_items", "staple_ingredients"])
def test_row_level_security_refuses_a_foreign_private_product_even_with_raw_sql(
    table, alice, bob, admin_db
):
    private = product(admin_db, "mój sos", 100, 1, 1, 20, user_id=alice.user_id)
    insert = text(f"INSERT INTO {table} (user_id, ingredient_id) VALUES (:u, :i)")

    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(bob.user_id) as conn:
        conn.execute(insert, {"u": bob.user_id, "i": private})


def test_row_level_security_hides_foreign_rows_from_a_bare_select(alice, bob, catalog):
    stock(alice, catalog, "mleko")
    stock(alice, catalog, "cukier", which="staples")

    with as_tenant(bob.user_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM pantry_items")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM staple_ingredients")).scalar_one() == 0
    with as_tenant(alice.user_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM pantry_items")).scalar_one() == 1


def test_the_default_list_is_read_only_for_the_application_role():
    with pytest.raises(DBAPIError, match="permission denied"), as_tenant(1) as conn:
        conn.execute(text("INSERT INTO default_staples (name) VALUES ('cukier')"))
