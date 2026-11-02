"""POST /recipes/import with the AI: real PostgreSQL and Redis; the web and the AI are faked."""

from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.main import app
from app.routers.recipe_import import get_page_fetcher, get_recipe_ai
from app.schemas.ai import AIRefinement
from app.services.ai_client import AIOutputError, AIUnavailable
from app.services.ai_extract import RecipeAI
from app.services.redis_client import get_redis
from tests.fakes import FakeLLM, full, ing, pl_flat_refinement
from tests.test_import import EN_GRAPH, MICRODATA, PL_FLAT, URL, FakeFetcher, do_import
from tests.test_ingredients import add_shared

NO_MARKUP = (Path(__file__).parent / "fixtures" / "recipes" / "no_markup_pl.html").read_bytes()
SOUP_URL = "https://kuchnia.example.test/zupa-ogorkowa"


def soup_recipe(**overrides):
    """What a good AI reads out of no_markup_pl.html."""
    data = {
        "title": "Zupa ogórkowa jak u babci",
        "description": "Klasyczna zupa ogórkowa z kwaszonych ogórków.",
        "servings": 4,
        "prep_time_min": 20,
        "cook_time_min": 40,
        "tags": ["zupa", "Obiad"],
        "steps": [
            "Ziemniaki i marchewkę obierz, pokrój w kostkę i zalej bulionem.",
            "Gotuj 20 minut, aż warzywa zmiękną.",
            "Ogórki zetrzyj na tarce, dodaj do zupy i gotuj jeszcze 15 minut.",
            "Zupę zabiel śmietaną i dopraw solą i pieprzem.",
        ],
        "ingredients": [
            ing(
                0,
                "500 g ziemniaków",
                qty=500,
                unit="g",
                product="ziemniak",
                macros=(77, 2.0, 0.1, 17.0),
            ),
            ing(
                1,
                "3 kwaszone ogórki",
                qty=3,
                unit="piece",
                product="ogórek kwaszony",
                macros=(11, 0.3, 0.2, 2.3),
            ),
            ing(
                2,
                "1 litr bulionu warzywnego",
                qty=1,
                unit="l",
                product="bulion warzywny",
                macros=(5, 0.2, 0.1, 0.8),
            ),
            ing(
                3,
                "2 łyżki śmietany 18%",
                qty=2,
                unit="tbsp",
                product="śmietana 18%",
                macros=(186, 2.5, 18.0, 3.4),
            ),
            ing(
                4, "1 marchewka", qty=1, unit="piece", product="marchew", macros=(41, 0.9, 0.2, 9.6)
            ),
            ing(
                5, "sól i pieprz do smaku", qty=None, unit=None, product="sól", macros=(0, 0, 0, 0)
            ),
        ],
    }
    data.update(overrides)
    return full(**data)


@pytest.fixture
def web():
    fetcher = FakeFetcher({URL: PL_FLAT, SOUP_URL: NO_MARKUP})
    app.dependency_overrides[get_page_fetcher] = lambda: fetcher
    yield fetcher
    app.dependency_overrides.pop(get_page_fetcher, None)


def use_ai(llm):
    """Make the API use a RecipeAI with this fake client (None = no API key configured)."""
    app.dependency_overrides[get_recipe_ai] = lambda: RecipeAI(llm, get_redis())
    return llm


@pytest.fixture(autouse=True)
def _reset_ai_override():
    yield
    app.dependency_overrides.pop(get_recipe_ai, None)


def products(admin_db, user_id=None):
    rows = admin_db.execute(
        text(
            "SELECT canonical_name, user_id, source FROM ingredients "
            "WHERE user_id IS NOT DISTINCT FROM :u ORDER BY canonical_name"
        ),
        {"u": user_id},
    )
    return [tuple(r) for r in rows]


# --- page WITH structured data: the AI takes the lines apart and tidies the steps ---
def test_ai_parses_ingredient_lines_and_links_products(alice, web, admin_db):
    use_ai(FakeLLM(pl_flat_refinement()))

    response = do_import(alice)

    assert response.status_code == 201
    body = response.json()
    assert body["ai_used"] is True and body["notice"] is None
    recipe = body["recipe"]
    assert recipe["import_method"] == "llm"  # AI shaped it, so it says so
    flour = recipe["ingredients"][0]
    assert flour["raw_text"] == "300 g mąki pszennej"  # the original text, from the markup
    assert (flour["quantity"], flour["unit"]) == (300.0, "g")
    assert flour["ingredient_name"] == "mąka pszenna" and flour["ingredient_id"] is not None
    assert [(i["quantity"], i["unit"]) for i in recipe["ingredients"][3:]] == [
        (1.0, "piece"),
        (1.0, "kg"),
        (2.0, "tbsp"),
        (1.0, "pinch"),
    ]
    assert [s["position"] for s in recipe["steps"]] == [1, 2, 3]
    assert recipe["steps"][0]["instruction"].startswith("Zagnieć mąkę, masło")


def test_markup_fields_are_kept_exactly_as_the_site_published_them(alice, web):
    use_ai(FakeLLM(pl_flat_refinement()))

    recipe = do_import(alice).json()["recipe"]

    assert recipe["title"] == "Szarlotka z kruszonką"
    assert recipe["servings"] == 8 and (recipe["prep_time_min"], recipe["cook_time_min"]) == (
        30,
        60,
    )
    assert recipe["tags"][:2] == ["deser", "polska"]
    assert recipe["image_url"] == "https://blog.example.test/img/szarlotka-1x1.jpg"
    assert recipe["source_nutrition"]["calories"] == "320 kcal"


def test_new_products_are_private_estimates_never_shared(alice, bob, web, admin_db):
    use_ai(FakeLLM(pl_flat_refinement()))

    do_import(alice)

    assert [(n, u, s) for n, u, s in products(admin_db, alice.user_id)] == [
        ("cukier puder", alice.user_id, "llm_estimate"),
        ("cynamon", alice.user_id, "llm_estimate"),
        ("jabłko", alice.user_id, "llm_estimate"),
        ("jajko", alice.user_id, "llm_estimate"),
        ("masło", alice.user_id, "llm_estimate"),
        ("mąka pszenna", alice.user_id, "llm_estimate"),
        ("sól", alice.user_id, "llm_estimate"),
    ]
    assert products(admin_db, None) == []  # the shared catalog is untouched
    assert [i["canonical_name"] for i in bob.get("/ingredients").json()["items"]] == []
    mine = alice.get("/ingredients", params={"q": "mąka"}).json()["items"][0]
    assert mine["source"] == "llm_estimate" and mine["is_shared"] is False


def test_existing_catalog_products_are_reused_not_duplicated(alice, web, admin_db):
    add_shared(admin_db, "masło", kcal=717)
    use_ai(FakeLLM(pl_flat_refinement()))

    recipe = do_import(alice).json()["recipe"]

    assert recipe["ingredients"][1]["ingredient_name"] == "masło"
    assert ("masło", None, "off") in products(admin_db, None)
    assert "masło" not in [n for n, _, _ in products(admin_db, alice.user_id)]


def test_a_similar_but_different_product_is_not_linked(alice, web, admin_db):
    add_shared(admin_db, "mąka pszenna razowa")
    use_ai(FakeLLM(pl_flat_refinement()))

    do_import(alice)

    own = [n for n, _, _ in products(admin_db, alice.user_id)]
    assert "mąka pszenna" in own  # a new private product, not the wholemeal flour


def test_other_users_private_products_are_invisible_to_the_matching(alice, bob, web, admin_db):
    bob.post(
        "/ingredients",
        json={
            "canonical_name": "jajko",
            "kcal_per_100g": 1,
            "protein_per_100g": 1,
            "fat_per_100g": 1,
            "carbs_per_100g": 1,
        },
    )
    use_ai(FakeLLM(pl_flat_refinement()))

    recipe = do_import(alice).json()["recipe"]

    egg = recipe["ingredients"][3]
    assert egg["ingredient_name"] == "jajko"
    mine = [r for r in products(admin_db, alice.user_id) if r[0] == "jajko"]
    assert mine == [("jajko", alice.user_id, "llm_estimate")]  # Alice's own, not Bob's


def test_implausible_macros_leave_the_line_unlinked_but_keep_quantity_and_unit(
    alice, web, admin_db
):
    broken = pl_flat_refinement()
    broken.ingredients[5] = ing(5, qty=2, unit="tbsp", product="cynamon", macros=(900, 90, 90, 90))
    use_ai(FakeLLM(broken))

    recipe = do_import(alice).json()["recipe"]

    cinnamon = recipe["ingredients"][5]
    assert cinnamon["ingredient_id"] is None and cinnamon["ingredient_name"] is None
    assert (cinnamon["quantity"], cinnamon["unit"]) == (2.0, "tbsp")
    assert "cynamon" not in [n for n, _, _ in products(admin_db, alice.user_id)]


def test_a_line_that_is_not_a_food_stays_unlinked(alice, web):
    refinement = pl_flat_refinement()
    refinement.ingredients[6] = ing(6, product=None, macros=None)
    use_ai(FakeLLM(refinement))

    line = do_import(alice).json()["recipe"]["ingredients"][6]

    assert line["ingredient_id"] is None and line["quantity"] is None


def test_a_wrong_answer_is_corrected_once(alice, web):
    llm = use_ai(FakeLLM(AIRefinement(steps=["x"], ingredients=[ing(0)]), pl_flat_refinement()))

    response = do_import(alice)

    assert response.status_code == 201 and response.json()["ai_used"] is True
    assert len(llm.calls) == 2


def test_two_wrong_answers_fail_cleanly_and_save_nothing(alice, web, admin_db):
    use_ai(FakeLLM(AIRefinement(steps=["x"], ingredients=[ing(0)])))

    response = do_import(alice)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ai_invalid_output"
    assert alice.get("/recipes").json()["total"] == 0
    assert products(admin_db, alice.user_id) == []


def test_an_unusable_answer_fails_cleanly(alice, web):
    use_ai(FakeLLM(AIOutputError("the AI declined to process this page")))

    response = do_import(alice)

    assert response.status_code == 502 and response.json()["detail"]["code"] == "ai_invalid_output"
    assert "declined" not in response.text  # internal detail is logged, not shown


def test_microdata_pages_go_through_the_ai_too(alice, web):
    web.pages[URL] = MICRODATA
    use_ai(
        FakeLLM(
            AIRefinement(
                steps=["Zagnieć ciasto."],
                ingredients=[ing(i, qty=1, unit="piece", product=f"produkt {i}") for i in range(6)],
            )
        )
    )

    recipe = do_import(alice).json()["recipe"]

    assert recipe["import_method"] == "llm" and recipe["title"] == "Pierogi ruskie z cebulką"


# --- page WITHOUT structured data: the AI reads the whole page ---
def test_the_ai_reads_a_page_without_any_markup(alice, web, admin_db):
    llm = use_ai(FakeLLM(soup_recipe()))

    response = do_import(alice, url=SOUP_URL)

    assert response.status_code == 201
    recipe = response.json()["recipe"]
    assert response.json()["ai_used"] is True and recipe["import_method"] == "llm"
    assert recipe["title"] == "Zupa ogórkowa jak u babci"
    assert recipe["servings"] == 4 and (recipe["prep_time_min"], recipe["cook_time_min"]) == (
        20,
        40,
    )
    assert recipe["tags"] == ["zupa", "obiad"]  # normalized
    assert (
        recipe["image_url"] == "https://kuchnia.example.test/zdjecia/zupa-ogorkowa.jpg"
    )  # og:image
    assert recipe["source_url"] == SOUP_URL
    assert [i["raw_text"] for i in recipe["ingredients"]][:2] == [
        "500 g ziemniaków",
        "3 kwaszone ogórki",
    ]
    assert recipe["ingredients"][0]["ingredient_name"] == "ziemniak"
    assert recipe["source_nutrition"] is None
    assert len(recipe["steps"]) == 4

    sent = llm.calls[0]["messages"][0]["content"]
    assert "500 g ziemniaków" in sent and "Zupa ogórkowa jak u babci" in sent
    for furniture in ("Kontakt", "do-not-read-this", "Wszelkie prawa", "Żurek"):
        assert furniture not in sent  # menu, scripts, footer and sidebar never reach the AI


def test_a_page_the_ai_says_has_no_recipe(alice, web):
    use_ai(FakeLLM(full(contains_recipe=False, title=None, steps=[], ingredients=[])))

    response = do_import(alice, url=SOUP_URL)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "no_recipe_data",
        "message": "No recipe was found on this page.",
    }
    assert alice.get("/recipes").json()["total"] == 0


def test_ingredients_invented_by_the_ai_are_caught(alice, web):
    invented = soup_recipe(
        ingredients=[ing(0, "5 g szafranu irańskiego z wyspy Kos", product="szafran")]
    )
    llm = use_ai(FakeLLM(invented, soup_recipe()))

    response = do_import(alice, url=SOUP_URL)

    assert response.status_code == 201 and len(llm.calls) == 2  # corrected on the second try
    assert response.json()["recipe"]["ingredients"][0]["raw_text"] == "500 g ziemniaków"


# --- cost: cache and re-imports ---
def test_refreshing_an_unchanged_page_does_not_pay_for_the_ai_again(alice, web):
    llm = use_ai(FakeLLM(pl_flat_refinement()))
    do_import(alice)

    refreshed = do_import(alice, refresh=True)

    assert refreshed.json()["status"] == "refreshed" and refreshed.json()["ai_used"] is True
    assert len(llm.calls) == 1  # identical input: the cached AI answer was reused


def test_a_changed_page_is_processed_again_and_known_products_are_reused(alice, web, admin_db):
    llm = use_ai(FakeLLM(pl_flat_refinement()))
    do_import(alice)
    web.pages[URL] = EN_GRAPH
    llm.answers = [
        AIRefinement(
            steps=["Boil.", "Fry."],
            ingredients=[ing(i, qty=1, unit="piece", product="jajko") for i in range(6)],
        )
    ]

    refreshed = do_import(alice, refresh=True)

    assert refreshed.status_code == 200 and len(llm.calls) == 2
    eggs = [r for r in products(admin_db, alice.user_id) if r[0] == "jajko"]
    assert len(eggs) == 1  # the same private product was found again, not duplicated


def test_an_already_saved_recipe_never_calls_the_ai(alice, web):
    llm = use_ai(FakeLLM(pl_flat_refinement()))
    do_import(alice)

    again = do_import(alice)

    assert again.json()["status"] == "existing" and again.json()["ai_used"] is False
    assert len(llm.calls) == 1


# --- the AI is not available ---
@pytest.mark.parametrize(
    ("error", "fragment"),
    [
        (AIUnavailable("ai_no_credit", "The AI account has no credit left."), "no credit left"),
        (AIUnavailable("ai_rate_limited", "The AI service is busy, try again later."), "busy"),
        (
            AIUnavailable("ai_unreachable", "The AI service could not be reached."),
            "could not be reached",
        ),
        (AIUnavailable("ai_not_configured", "The AI key is invalid or not allowed."), "invalid"),
    ],
)
def test_page_with_markup_is_saved_in_basic_form_when_the_ai_is_unavailable(
    alice, web, error, fragment
):
    use_ai(FakeLLM(error))

    response = do_import(alice)

    assert response.status_code == 201
    body = response.json()
    assert body["ai_used"] is False
    assert fragment in body["notice"] and "basic version" in body["notice"]
    recipe = body["recipe"]
    assert recipe["import_method"] == "jsonld"  # not marked as AI work
    assert recipe["title"] == "Szarlotka z kruszonką" and len(recipe["steps"]) == 3
    line = recipe["ingredients"][0]
    assert line["raw_text"] == "300 g mąki pszennej" and line["quantity"] is None
    assert line["ingredient_id"] is None


def test_without_an_api_key_markup_pages_still_import(alice, web):
    use_ai(None)

    response = do_import(alice)

    assert response.status_code == 201
    assert response.json()["ai_used"] is False and "not configured" in response.json()["notice"]


def test_a_basic_import_can_be_upgraded_later_with_refresh(alice, web):
    use_ai(FakeLLM(AIUnavailable("ai_rate_limited", "The AI service is busy, try again later.")))
    basic = do_import(alice).json()["recipe"]
    app.dependency_overrides.pop(get_recipe_ai)
    use_ai(FakeLLM(pl_flat_refinement()))

    upgraded = do_import(alice, refresh=True).json()["recipe"]

    assert upgraded["id"] == basic["id"] and upgraded["import_method"] == "llm"
    assert upgraded["ingredients"][0]["quantity"] == 300.0


def test_page_without_markup_cannot_be_imported_when_the_ai_is_unavailable(alice, web):
    use_ai(FakeLLM(AIUnavailable("ai_no_credit", "The AI account has no credit left.")))

    response = do_import(alice, url=SOUP_URL)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "ai_unavailable" and "no credit left" in detail["message"]
    assert "cannot be imported without AI" in detail["message"]


def test_page_without_markup_and_without_an_ai_is_the_plain_no_data_error(alice, web):
    use_ai(None)

    response = do_import(alice, url=SOUP_URL)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_recipe_data"
    assert "AI import is not available" in response.json()["detail"]["message"]


def test_the_daily_ai_limit_degrades_to_the_basic_import(alice, web, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit_per_user", 1)
    web.pages[URL + "-2"] = EN_GRAPH  # different content, so no cached AI answer applies
    use_ai(FakeLLM(pl_flat_refinement()))

    first = do_import(alice).json()
    second = do_import(alice, url=URL + "-2").json()

    assert first["ai_used"] is True
    assert second["ai_used"] is False and "daily limit of 1" in second["notice"]
    assert second["recipe"]["title"] == "Weeknight Lemon Chickpea Pasta"  # still imported


def test_the_default_dependency_without_a_key_reports_the_ai_as_unavailable(alice, web):
    # No override at all: the real dependency runs, and the tests have a blank API key.
    response = do_import(alice)

    assert response.status_code == 201
    assert response.json()["ai_used"] is False and "not configured" in response.json()["notice"]
