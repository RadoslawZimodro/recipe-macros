"""The food log: recording, the sums per day (calendar days in Polish time), the comparison with
the goals, isolation between users. Every expected number is worked out by hand in a comment."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.main import app
from tests.seed import line, product
from tests.test_recipes import create
from tests.test_rls import as_tenant

# Three moments chosen around midnight in Poland (CET = UTC+1 in March, CEST = UTC+2 in June).
LATE_MARCH_10 = "2026-03-10T23:30:00+01:00"  # 22:30 UTC, the 10th
EARLY_MARCH_11 = "2026-03-11T00:30:00+01:00"  # 23:30 UTC on the 10th, but the 11th in Poland
EARLY_JUNE_15 = "2026-06-15T00:30:00+02:00"  # 22:30 UTC on the 14th, the 15th in Poland


@pytest.fixture
def catalog(admin_db):
    return {
        "flour": product(admin_db, "mąka pszenna", 364, 10.3, 1.0, 76.3),
        "butter": product(admin_db, "masło", 717, 0.9, 81, 0.1),
        "rice": product(admin_db, "ryż", 360, 7, 1, 80),
    }


@pytest.fixture
def pancakes(alice, catalog):
    """200 g flour + 100 g butter, 4 servings.
    Total: kcal 728 + 717 = 1445, protein 20.6 + 0.9 = 21.5, fat 2 + 81 = 83, carbs 152.6 + 0.1.
    One serving: kcal 361.25, protein 5.375, fat 20.75, carbs 38.175."""
    return create(
        alice,
        title="Placki",
        servings=4,
        ingredients=[
            line("200 g mąki", qty=200, unit="g", product_id=catalog["flour"]),
            line("100 g masła", qty=100, unit="g", product_id=catalog["butter"]),
        ],
    )


def log_recipe(client, recipe, servings=1, when=None):
    body = {"recipe_id": recipe["id"], "servings": servings}
    if when:
        body["logged_at"] = when
    response = client.post("/food-log", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def log_product(client, product_id, grams, when=None):
    body = {"ingredient_id": product_id, "grams": grams}
    if when:
        body["logged_at"] = when
    response = client.post("/food-log", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def day(client, date=None):
    response = client.get("/food-log", params={"date": date} if date else {})
    assert response.status_code == 200, response.text
    return response.json()


# --- recording ---
def test_servings_of_a_recipe_are_worked_out_from_its_lines(alice, pancakes):
    entry = log_recipe(alice, pancakes, servings=2)

    # 2 of 4 servings = half: kcal 722.5, protein 10.75 -> 10.8, fat 41.5, carbs 76.35 -> 76.4
    assert entry["kind"] == "recipe" and entry["name"] == "Placki" and entry["servings"] == 2
    assert entry["nutrition"] == {"kcal": 722.5, "protein": 10.8, "fat": 41.5, "carbs": 76.4}
    assert entry["complete"] is True and entry["lines_total"] == entry["lines_counted"] == 2


def test_grams_of_a_product_are_worked_out_from_its_label(alice, catalog):
    entry = log_product(alice, catalog["rice"], 150)

    # 150 g of rice: kcal 540, protein 10.5, fat 1.5, carbs 120
    assert entry["kind"] == "product" and entry["name"] == "ryż" and entry["grams"] == 150
    assert entry["nutrition"] == {"kcal": 540.0, "protein": 10.5, "fat": 1.5, "carbs": 120.0}
    assert entry["is_estimate"] is False and entry["lines_total"] is None


def test_a_product_that_is_an_ai_guess_is_marked(alice, admin_db):
    guess = product(
        admin_db, "dziwny sos", 100, 1, 1, 20, user_id=alice.user_id, source="llm_estimate"
    )

    assert log_product(alice, guess, 50)["is_estimate"] is True


def test_optional_lines_do_not_count(alice, catalog):
    recipe = create(
        alice,
        servings=1,
        ingredients=[
            line("100 g ryżu", qty=100, unit="g", product_id=catalog["rice"]),
            line("100 g masła", qty=100, unit="g", product_id=catalog["butter"], optional=True),
        ],
    )

    assert log_recipe(alice, recipe)["nutrition"]["kcal"] == 360.0


def test_a_recipe_with_lines_that_cannot_be_computed_is_flagged_incomplete(alice, catalog):
    recipe = create(
        alice,
        servings=1,
        ingredients=[
            line("100 g masła", qty=100, unit="g", product_id=catalog["butter"]),
            line("sól do smaku"),
        ],
    )

    entry = log_recipe(alice, recipe)

    assert entry["nutrition"]["kcal"] == 717.0  # what is known
    assert entry["complete"] is False and (entry["lines_counted"], entry["lines_total"]) == (1, 2)
    assert day(alice)["totals"]["complete"] is False


def test_a_recipe_where_nothing_can_be_computed_has_no_nutrition(alice):
    recipe = create(alice, servings=1, ingredients=[line("sól do smaku"), line("pieprz")])

    entry = log_recipe(alice, recipe)

    assert entry["nutrition"] is None and entry["complete"] is False
    assert day(alice)["totals"]["total"]["kcal"] == 0.0


# --- validation ---
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"recipe_id": 1},
        {"servings": 2},
        {"ingredient_id": 1},
        {"grams": 100},
        {"recipe_id": 1, "servings": 1, "ingredient_id": 1, "grams": 100},
        {"recipe_id": 1, "servings": 1, "grams": 100},
        {"recipe_id": 1, "servings": 0},
        {"recipe_id": 1, "servings": -1},
        {"recipe_id": 1, "servings": 101},
        {"ingredient_id": 1, "grams": 0},
        {"ingredient_id": 1, "grams": 10001},
        {"ingredient_id": 1, "grams": 100, "logged_at": "2026-03-10T12:00:00"},  # no time zone
        {"ingredient_id": 1, "grams": 100, "logged_at": "2099-01-01T12:00:00+01:00"},  # far future
    ],
)
def test_invalid_entries_are_refused(alice, body):
    assert alice.post("/food-log", json=body).status_code == 422


def test_an_unknown_recipe_or_product_is_not_found(alice):
    assert alice.post("/food-log", json={"recipe_id": 999, "servings": 1}).status_code == 404
    assert alice.post("/food-log", json={"ingredient_id": 999, "grams": 1}).status_code == 404


def test_a_deleted_recipe_cannot_be_logged_any_more(alice, pancakes):
    alice.delete(f"/recipes/{pancakes['id']}")

    assert (
        alice.post("/food-log", json={"recipe_id": pancakes["id"], "servings": 1}).status_code
        == 404
    )


# --- days: the calendar day is a Polish one ---
def test_the_day_follows_polish_midnight_not_utc(alice, pancakes, catalog):
    log_recipe(alice, pancakes, when=LATE_MARCH_10)
    log_product(alice, catalog["rice"], 150, when=EARLY_MARCH_11)

    tenth, eleventh = day(alice, "2026-03-10"), day(alice, "2026-03-11")

    # 00:30 on the 11th in Poland is still the 10th in UTC, but it belongs to the 11th
    assert [e["name"] for e in tenth["entries"]] == ["Placki"]
    assert [e["name"] for e in eleventh["entries"]] == ["ryż"]
    assert tenth["totals"]["total"]["kcal"] == 361.3  # one serving: 361.25
    assert eleventh["totals"]["total"]["kcal"] == 540.0
    assert tenth["timezone"] == "Europe/Warsaw"


def test_summer_time_is_handled(alice, catalog):
    log_product(alice, catalog["rice"], 100, when=EARLY_JUNE_15)  # 22:30 UTC on the 14th

    assert day(alice, "2026-06-15")["totals"]["entries"] == 1
    assert day(alice, "2026-06-14")["totals"]["entries"] == 0


def test_the_day_totals_add_up_the_entries(alice, pancakes, catalog):
    log_recipe(alice, pancakes, servings=1, when="2026-03-10T08:00:00+01:00")
    log_product(alice, catalog["rice"], 150, when="2026-03-10T13:00:00+01:00")
    log_product(alice, catalog["butter"], 10, when="2026-03-10T19:00:00+01:00")

    result = day(alice, "2026-03-10")

    # kcal 361.25 + 540 + 71.7 = 972.95 -> 973.0 (half up); protein 5.375 + 10.5 + 0.09 = 15.965,
    # fat 20.75 + 1.5 + 8.1 = 30.35, carbs 38.175 + 120 + 0.01 = 158.185
    assert [e["name"] for e in result["entries"]] == ["Placki", "ryż", "masło"]  # by time
    assert result["totals"]["entries"] == 3
    assert result["totals"]["total"] == {
        "kcal": 973.0,
        "protein": 16.0,
        "fat": 30.4,
        "carbs": 158.2,
    }
    assert result["totals"]["complete"] is True


def test_the_default_day_is_today(alice, catalog):
    log_product(alice, catalog["rice"], 100)  # logged now

    assert [e["name"] for e in day(alice)["entries"]] == ["ryż"]


def test_a_range_of_days_contains_the_empty_days_too(alice, pancakes, catalog):
    log_recipe(alice, pancakes, when=LATE_MARCH_10)
    log_product(alice, catalog["rice"], 150, when=EARLY_MARCH_11)

    response = alice.get("/food-log/days", params={"from": "2026-03-09", "to": "2026-03-12"})
    days = response.json()["days"]

    assert [d["day"] for d in days] == ["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"]
    assert [d["entries"] for d in days] == [0, 1, 1, 0]
    assert [d["total"]["kcal"] for d in days] == [0.0, 361.3, 540.0, 0.0]
    assert days[0]["complete"] is True and days[0]["is_estimate"] is False


def test_the_range_is_validated(alice):
    def ask(date_from, date_to):
        return alice.get("/food-log/days", params={"from": date_from, "to": date_to})

    assert ask("2026-03-12", "2026-03-09").status_code == 422
    assert ask("2026-01-01", "2027-01-02").status_code == 422  # 367 days; 366 is the most
    assert ask("2026-01-01", "2026-12-31").status_code == 200
    assert alice.get("/food-log/days", params={"from": "2026-03-01"}).status_code == 422


# --- goals ---
def set_goals(client, **goals):
    response = client.patch("/auth/me/goals", json=goals)
    assert response.status_code == 200, response.text
    return response.json()


def test_without_goals_there_is_nothing_to_compare(alice, catalog):
    log_product(alice, catalog["rice"], 150, when=EARLY_MARCH_11)

    totals = day(alice, "2026-03-11")["totals"]

    assert totals["kcal"] is None and totals["protein"] is None


def test_the_day_is_compared_with_the_goals(alice, catalog):
    set_goals(alice, daily_kcal_goal=2000, daily_protein_goal=100)
    log_product(alice, catalog["rice"], 150, when=EARLY_MARCH_11)

    totals = day(alice, "2026-03-11")["totals"]

    # 540 of 2000 kcal = 27.0%, 1460 left; 10.5 of 100 g protein = 10.5%, 89.5 left
    assert totals["kcal"] == {"goal": 2000, "eaten": 540.0, "remaining": 1460.0, "percent": 27.0}
    assert totals["protein"] == {"goal": 100, "eaten": 10.5, "remaining": 89.5, "percent": 10.5}


def test_exceeding_the_goal_gives_a_negative_remainder(alice, catalog):
    set_goals(alice, daily_kcal_goal=500)
    log_product(alice, catalog["rice"], 150, when=EARLY_MARCH_11)

    kcal = day(alice, "2026-03-11")["totals"]["kcal"]

    assert kcal["remaining"] == -40.0 and kcal["percent"] == 108.0


def test_the_goals_apply_to_every_day_of_a_range(alice, catalog):
    set_goals(alice, daily_kcal_goal=2000)

    days = alice.get("/food-log/days", params={"from": "2026-03-10", "to": "2026-03-11"}).json()

    assert [d["kcal"]["remaining"] for d in days["days"]] == [2000.0, 2000.0]
    assert days["days"][0]["protein"] is None


def test_goals_can_be_changed_one_at_a_time_and_cleared(alice):
    set_goals(alice, daily_kcal_goal=2000, daily_protein_goal=100)

    after_protein = set_goals(alice, daily_protein_goal=120)
    cleared = set_goals(alice, daily_kcal_goal=None)

    assert (after_protein["daily_kcal_goal"], after_protein["daily_protein_goal"]) == (2000, 120)
    assert (cleared["daily_kcal_goal"], cleared["daily_protein_goal"]) == (None, 120)
    assert alice.get("/auth/me").json()["daily_protein_goal"] == 120


@pytest.mark.parametrize(
    "body",
    [
        {"daily_kcal_goal": 100},
        {"daily_kcal_goal": 20000},
        {"daily_protein_goal": 0},
        {"daily_protein_goal": 5000},
    ],
)
def test_unreasonable_goals_are_refused(alice, body):
    assert alice.patch("/auth/me/goals", json=body).status_code == 422


def test_goals_are_personal(alice, bob):
    set_goals(alice, daily_kcal_goal=2000)

    assert bob.get("/auth/me").json()["daily_kcal_goal"] is None


# --- live computation: corrections reach the history ---
def test_correcting_a_recipe_line_corrects_the_logged_day(alice, pancakes):
    log_recipe(alice, pancakes, when=LATE_MARCH_10)
    flour_line = pancakes["ingredients"][0]["id"]

    alice.patch(f"/recipes/{pancakes['id']}/ingredients/{flour_line}", json={"grams": 400})

    # 400 g flour = 1456 kcal; total 1456 + 717 = 2173; one of four servings = 543.25 -> 543.3
    assert day(alice, "2026-03-10")["totals"]["total"]["kcal"] == 543.3


def test_correcting_a_product_corrects_the_logged_day(alice, admin_db):
    own = product(admin_db, "mój ryż", 360, 7, 1, 80, user_id=alice.user_id)
    log_product(alice, own, 100, when=EARLY_MARCH_11)

    alice.patch(f"/ingredients/{own}", json={"kcal_per_100g": 200})

    assert day(alice, "2026-03-11")["totals"]["total"]["kcal"] == 200.0  # 100 g at 200 kcal


def test_a_deleted_recipe_still_counts_in_the_history(alice, pancakes):
    log_recipe(alice, pancakes, when=LATE_MARCH_10)

    alice.delete(f"/recipes/{pancakes['id']}")

    entry = day(alice, "2026-03-10")["entries"][0]
    assert entry["name"] == "Placki" and entry["nutrition"]["kcal"] == 361.3


# --- deleting ---
def test_an_entry_can_be_deleted(alice, catalog):
    entry = log_product(alice, catalog["rice"], 100, when=EARLY_MARCH_11)

    assert alice.delete(f"/food-log/{entry['id']}").status_code == 204
    assert day(alice, "2026-03-11")["entries"] == []
    assert alice.delete(f"/food-log/{entry['id']}").status_code == 404


# --- isolation and access ---
def test_users_do_not_see_each_others_entries(alice, bob, catalog):
    entry = log_product(alice, catalog["rice"], 100, when=EARLY_MARCH_11)

    assert day(bob, "2026-03-11")["entries"] == []
    assert day(bob, "2026-03-11")["totals"]["entries"] == 0
    assert bob.delete(f"/food-log/{entry['id']}").status_code == 404
    assert len(day(alice, "2026-03-11")["entries"]) == 1  # still there


def test_someone_elses_recipe_or_private_product_cannot_be_logged(alice, bob, admin_db):
    recipe = create(alice, title="Prywatny")
    private = product(admin_db, "mój sos", 100, 1, 1, 20, user_id=alice.user_id)

    assert bob.post("/food-log", json={"recipe_id": recipe["id"], "servings": 1}).status_code == 404
    assert bob.post("/food-log", json={"ingredient_id": private, "grams": 10}).status_code == 404


def test_the_endpoints_need_a_session_and_the_csrf_header(alice, catalog):
    anonymous = TestClient(app)
    assert anonymous.get("/food-log").status_code == 401
    assert (
        anonymous.get(
            "/food-log/days", params={"from": "2026-03-01", "to": "2026-03-02"}
        ).status_code
        == 401
    )
    assert anonymous.post("/food-log", json={"ingredient_id": 1, "grams": 1}).status_code == 401
    assert anonymous.delete("/food-log/1").status_code == 401

    alice.headers.pop("X-CSRF-Token")
    body = {"ingredient_id": catalog["rice"], "grams": 100}
    assert alice.post("/food-log", json=body).status_code == 403


# --- the database enforces the rules itself ---
def test_the_database_requires_exactly_one_kind_of_entry(admin_db, alice, catalog, pancakes):
    both = text(
        "INSERT INTO food_logs (user_id, recipe_id, servings, ingredient_id, grams) "
        "VALUES (:u, :r, 1, :i, 100)"
    )
    neither = text("INSERT INTO food_logs (user_id) VALUES (:u)")

    with pytest.raises(IntegrityError, match="exactly_one_source"):
        admin_db.execute(both, {"u": alice.user_id, "r": pancakes["id"], "i": catalog["rice"]})
    admin_db.rollback()
    with pytest.raises(IntegrityError, match="exactly_one_source"):
        admin_db.execute(neither, {"u": alice.user_id})
    admin_db.rollback()


def test_row_level_security_refuses_a_foreign_recipe_even_with_raw_sql(alice, bob):
    recipe = create(alice, title="Alice's")
    insert = text("INSERT INTO food_logs (user_id, recipe_id, servings) VALUES (:u, :r, 1)")

    with pytest.raises(DBAPIError, match="row-level security"), as_tenant(bob.user_id) as conn:
        conn.execute(insert, {"u": bob.user_id, "r": recipe["id"]})  # bob's own row, alice's recipe


def test_row_level_security_hides_foreign_rows_from_a_bare_select(alice, bob, catalog):
    log_product(alice, catalog["rice"], 100)

    with as_tenant(bob.user_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM food_logs")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM food_log_nutrition")).scalar_one() == 0
    with as_tenant(alice.user_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM food_log_nutrition")).scalar_one() == 1
