"""Recipe CRUD through the API, against a real PostgreSQL with Row-Level Security."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def recipe_payload(**overrides):
    payload = {
        "title": "Naleśniki",
        "description": "Cienkie, na słodko.",
        "servings": 4,
        "prep_time_min": 10,
        "cook_time_min": 20,
        "tags": ["deser", "Śniadanie"],
        "steps": [{"instruction": "Wymieszaj składniki."}, {"instruction": "Smaż na patelni."}],
        "ingredients": [
            {"raw_text": "200 g mąki", "quantity": 200, "unit": "g"},
            {"raw_text": "2 jajka", "quantity": 2, "unit": "piece"},
            {"raw_text": "szczypta soli", "unit": "pinch", "is_optional": True},
        ],
    }
    payload.update(overrides)
    return payload


def create(client, **overrides):
    response = client.post("/recipes", json=recipe_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# --- create / read ---
def test_create_returns_full_recipe_with_ordered_children(alice):
    recipe = create(alice)

    assert recipe["title"] == "Naleśniki"
    assert recipe["import_method"] == "manual"
    assert recipe["tags"] == ["deser", "śniadanie"]  # normalized to lower case
    assert [s["position"] for s in recipe["steps"]] == [1, 2]
    assert [s["instruction"] for s in recipe["steps"]] == [
        "Wymieszaj składniki.",
        "Smaż na patelni.",
    ]
    assert [i["position"] for i in recipe["ingredients"]] == [1, 2, 3]
    assert recipe["ingredients"][0] == {
        "id": recipe["ingredients"][0]["id"],
        "position": 1,
        "raw_text": "200 g mąki",
        "quantity": 200.0,
        "unit": "g",
        "is_optional": False,
        "ingredient_id": None,
        "ingredient_name": None,
    }
    assert recipe["ingredients"][2]["is_optional"] is True


def test_get_returns_the_same_recipe(alice):
    created = create(alice)

    assert alice.get(f"/recipes/{created['id']}").json() == created


def test_minimal_recipe_gets_defaults(alice):
    bare = alice.post("/recipes", json={"title": "Woda"}).json()
    assert bare["servings"] == 1
    assert bare["steps"] == [] and bare["ingredients"] == [] and bare["tags"] == []


def test_blank_optional_fields_become_null(alice):
    recipe = create(alice, description="   ", source_url="", image_url=" ")

    assert recipe["description"] is None
    assert recipe["source_url"] is None
    assert recipe["image_url"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "   "},
        {"title": "x" * 301},
        {"servings": 0},
        {"prep_time_min": -1},
        {"source_url": "javascript:alert(1)"},
        {"source_url": "ftp://example.com/x"},
        {"image_url": "not a url"},
        {"steps": [{"instruction": "  "}]},
        {"ingredients": [{"raw_text": ""}]},
        {"ingredients": [{"raw_text": "x", "quantity": -1}]},
        {"tags": ["x" * 51]},
        {"user_id": 999},  # unknown fields are rejected, never trusted
    ],
)
def test_invalid_payload_is_rejected(alice, overrides):
    assert alice.post("/recipes", json=recipe_payload(**overrides)).status_code == 422


def test_unknown_unit_is_rejected(alice):
    response = alice.post(
        "/recipes", json=recipe_payload(ingredients=[{"raw_text": "x", "unit": "bucket"}])
    )

    assert response.status_code == 422
    assert "bucket" in response.json()["detail"]


def test_duplicate_tags_are_collapsed(alice):
    assert create(alice, tags=["a", "A", " a "])["tags"] == ["a"]


# --- update (PUT) ---
def test_put_replaces_scalars_steps_and_lines(alice):
    created = create(alice)

    response = alice.put(
        f"/recipes/{created['id']}",
        json=recipe_payload(
            title="Pankejki",
            servings=2,
            tags=[],
            steps=[{"instruction": "Jedyny krok."}],
            ingredients=[{"raw_text": "mleko", "quantity": 0.5, "unit": "l"}],
        ),
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["id"] == created["id"]
    assert updated["title"] == "Pankejki" and updated["servings"] == 2 and updated["tags"] == []
    assert updated["steps"] == [{"position": 1, "instruction": "Jedyny krok."}]
    assert [i["raw_text"] for i in updated["ingredients"]] == ["mleko"]
    assert updated["ingredients"][0]["quantity"] == 0.5
    assert updated["updated_at"] > created["updated_at"]  # set by the DB trigger


def test_put_can_reorder_steps(alice):
    created = create(alice)
    reordered = list(reversed(created["steps"]))

    updated = alice.put(
        f"/recipes/{created['id']}",
        json=recipe_payload(steps=[{"instruction": s["instruction"]} for s in reordered]),
    ).json()

    assert [s["instruction"] for s in updated["steps"]] == [s["instruction"] for s in reordered]
    assert [s["position"] for s in updated["steps"]] == [1, 2]


def test_put_unknown_recipe_is_404(alice):
    assert alice.put("/recipes/999", json=recipe_payload()).status_code == 404


def test_updated_at_trigger_also_fires_for_raw_sql_updates(alice, admin_db):
    created = create(alice)

    admin_db.execute(
        text("UPDATE recipes SET title = 'Zmieniony' WHERE id = :id"), {"id": created["id"]}
    )
    admin_db.commit()

    after = alice.get(f"/recipes/{created['id']}").json()
    assert after["title"] == "Zmieniony"
    assert after["updated_at"] > created["updated_at"]


# --- delete (soft) ---
def test_delete_hides_the_recipe_but_keeps_the_row(alice, admin_db):
    created = create(alice)

    assert alice.delete(f"/recipes/{created['id']}").status_code == 204

    assert alice.get(f"/recipes/{created['id']}").status_code == 404
    assert alice.get("/recipes").json()["items"] == []
    assert alice.delete(f"/recipes/{created['id']}").status_code == 404
    assert alice.put(f"/recipes/{created['id']}", json=recipe_payload()).status_code == 404
    stored = admin_db.execute(
        text("SELECT deleted_at IS NOT NULL FROM recipes WHERE id = :id"), {"id": created["id"]}
    ).scalar_one()
    assert stored is True


# --- source_url uniqueness (the upsert key of the import step) ---
def test_same_source_url_twice_conflicts_but_is_allowed_after_delete(alice):
    url = "https://example.com/przepis"
    first = create(alice, source_url=url)

    assert alice.post("/recipes", json=recipe_payload(source_url=url)).status_code == 409

    alice.delete(f"/recipes/{first['id']}")
    assert alice.post("/recipes", json=recipe_payload(source_url=url)).status_code == 201


def test_different_users_may_save_the_same_source_url(alice, bob):
    url = "https://example.com/przepis"

    assert alice.post("/recipes", json=recipe_payload(source_url=url)).status_code == 201
    assert bob.post("/recipes", json=recipe_payload(source_url=url)).status_code == 201


def test_recipes_without_source_url_do_not_conflict(alice):
    create(alice)
    create(alice)


# --- list / search / pagination ---
def test_list_is_newest_first_and_paginated(alice):
    for title in ("A", "B", "C"):
        create(alice, title=title)

    first = alice.get("/recipes", params={"limit": 2}).json()
    second = alice.get("/recipes", params={"limit": 2, "offset": 2}).json()

    assert first["total"] == 3 and first["limit"] == 2 and first["offset"] == 0
    assert [r["title"] for r in first["items"]] == ["C", "B"]
    assert [r["title"] for r in second["items"]] == ["A"]
    assert "steps" not in first["items"][0]  # summaries carry no children


def test_pagination_limits_are_validated(alice):
    assert alice.get("/recipes", params={"limit": 0}).status_code == 422
    assert alice.get("/recipes", params={"limit": 101}).status_code == 422
    assert alice.get("/recipes", params={"offset": -1}).status_code == 422


def test_search_finds_substrings_case_insensitively(alice):
    for title in ("Zupa pomidorowa", "Kotlet schabowy", "Pomidory faszerowane"):
        create(alice, title=title)

    result = alice.get("/recipes", params={"q": "POMIDOR"}).json()

    assert result["total"] == 2
    assert {r["title"] for r in result["items"]} == {"Zupa pomidorowa", "Pomidory faszerowane"}


def test_search_tolerates_typos_through_trigram_similarity(alice):
    create(alice, title="Spaghetti carbonara")
    create(alice, title="Kotlet schabowy")

    result = alice.get("/recipes", params={"q": "spagetti carbonra"}).json()

    assert [r["title"] for r in result["items"]] == ["Spaghetti carbonara"]


def test_search_treats_like_wildcards_literally(alice):
    create(alice, title="Sok 100% jabłkowy")
    create(alice, title="Sok pomarańczowy")

    assert alice.get("/recipes", params={"q": "100%"}).json()["total"] == 1
    assert alice.get("/recipes", params={"q": "_ok"}).json()["total"] == 0


def test_search_ranks_the_closest_title_first(alice):
    create(alice, title="Zupa pomidorowa z ryżem i warzywami")
    create(alice, title="Zupa pomidorowa")

    titles = [
        r["title"] for r in alice.get("/recipes", params={"q": "zupa pomidorowa"}).json()["items"]
    ]

    assert titles[0] == "Zupa pomidorowa"


def test_filter_by_tag(alice):
    create(alice, title="A", tags=["obiad", "włoska"])
    create(alice, title="B", tags=["deser"])

    result = alice.get("/recipes", params={"tag": " Obiad "}).json()

    assert [r["title"] for r in result["items"]] == ["A"]
    assert result["total"] == 1


def test_search_and_tag_combine_with_total(alice):
    create(alice, title="Zupa jarzynowa", tags=["zupa"])
    create(alice, title="Zupa rybna", tags=["ryby"])

    result = alice.get("/recipes", params={"q": "zupa", "tag": "ryby"}).json()

    assert [r["title"] for r in result["items"]] == ["Zupa rybna"]
    assert result["total"] == 1


# --- auth / CSRF ---
def test_all_endpoints_require_a_session(client):
    assert client.get("/recipes").status_code == 401
    assert client.get("/recipes/1").status_code == 401
    assert client.post("/recipes", json=recipe_payload()).status_code == 401
    assert client.put("/recipes/1", json=recipe_payload()).status_code == 401
    assert client.delete("/recipes/1").status_code == 401


def test_writes_require_the_csrf_header(alice):
    created = create(alice)
    del alice.headers["X-CSRF-Token"]

    assert alice.post("/recipes", json=recipe_payload()).status_code == 403
    assert alice.put(f"/recipes/{created['id']}", json=recipe_payload()).status_code == 403
    assert alice.delete(f"/recipes/{created['id']}").status_code == 403
    assert alice.get(f"/recipes/{created['id']}").status_code == 200  # reads need no CSRF


@pytest.mark.parametrize("method", ["jsonld", "microdata", "llm", "manual"])
def test_database_accepts_every_known_import_method(alice, admin_db, method):
    admin_db.execute(
        text("INSERT INTO recipes (user_id, title, import_method) VALUES (:u, 'x', :m)"),
        {"u": alice.user_id, "m": method},
    )


def test_database_rejects_an_unknown_import_method(alice, admin_db):
    with pytest.raises(DBAPIError, match="ck_recipes_import_method"):
        admin_db.execute(
            text("INSERT INTO recipes (user_id, title, import_method) VALUES (:u, 'x', 'xml')"),
            {"u": alice.user_id},
        )
