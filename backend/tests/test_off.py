"""Open Food Facts import: the starter list, picking the median, the polite client, the writes.
No test touches the real Open Food Facts server."""

import httpx2
import pytest
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db import engine as app_engine
from app.services.off import (
    DATA_FILE,
    MIN_PRODUCTS,
    Entry,
    OffClient,
    OffError,
    OffProduct,
    estimate,
    load_entries,
    parse_products,
)
from app.services.off_import import import_catalog
from app.services.products import normalize_name, plausible_density, plausible_unit_weight
from tests.conftest import TEST_ADMIN_URL
from tests.seed import line
from tests.test_nutrition import nutrition, recipe_with


def entry(name="mąka pszenna", query=None, **kw):
    defaults = dict(
        name=name, off_query=query or name, exclude=(), density=None,
        piece_g=None, clove_g=None, slice_g=None, fixed=None,
    )  # fmt: skip
    return Entry(**{**defaults, **kw})


def product(name, kcal, protein, fat, carbs, poland=True):
    return OffProduct(name, kcal, protein, fat, carbs, poland)


def payload(*items):
    """An OFF search answer; each item is (name, kcal, protein, fat, carbs[, countries])."""
    products = []
    for name, kcal, protein, fat, carbs, *rest in items:
        products.append(
            {
                "product_name": name,
                "nutriments": {
                    "energy-kcal_100g": kcal,
                    "proteins_100g": protein,
                    "fat_100g": fat,
                    "carbohydrates_100g": carbs,
                },
                "countries_tags": rest[0] if rest else ["en:poland"],
            }
        )
    return {"products": products}


FLOURS = [
    ("Mąka pszenna Basia", 341, 10, 1, 71.7),
    ("Mąka pszenna tortowa", 346, 11.3, 0.9, 72.5),
    ("Mąka pszenna typ 500", 347, 10, 1.2, 74),
    ("Mąka pszenna", 350, 12, 1.2, 72),
    ("Mąka pszenna Szymanowska", 340, 11, 1.2, 70),
]


# --- the starter list is data too: it is checked ---
def test_the_starter_list_is_well_formed():
    entries = load_entries()

    assert len(entries) >= 50
    names = [e.name for e in entries]
    assert len({n.casefold() for n in names}) == len(names), "duplicate names"
    for e in entries:
        assert e.name == normalize_name(e.name), f"{e.name!r} is not in normalized form"
        assert e.off_query or e.fixed, e.name
        assert e.density is None or plausible_density(e.density), e.name
        for unit, grams in (("piece", e.piece_g), ("clove", e.clove_g), ("slice", e.slice_g)):
            assert grams is None or plausible_unit_weight(unit, grams), (e.name, unit)


def test_the_list_contains_the_basics_with_sensible_numbers():
    by_name = {e.name: e for e in load_entries()}

    assert by_name["jajko"].piece_g == 55 and by_name["czosnek"].clove_g == 5
    assert by_name["miód"].density == 1.42 and by_name["mąka pszenna"].density == 0.53
    assert by_name["woda"].fixed == (0, 0, 0, 0) and by_name["sól"].fixed == (0, 0, 0, 0)
    assert "orzechowe" in by_name["masło"].exclude  # peanut butter is not butter


def test_a_malformed_list_is_refused(tmp_path):
    header = (
        "name,off_query,exclude,density_g_per_ml,piece_g,clove_g,slice_g,kcal,protein,fat,carbs\n"
    )
    short = tmp_path / "short.csv"
    short.write_text(header + "mąka,mąka,,0.5\n", encoding="utf-8")
    partial = tmp_path / "partial.csv"
    partial.write_text(header + "sól,sól,,1.2,,,,0,0,,\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wrong number of columns"):
        load_entries(short)
    with pytest.raises(ValueError, match="all four values or none"):
        load_entries(partial)


def test_data_file_is_inside_the_package():
    assert DATA_FILE.exists() and DATA_FILE.suffix == ".csv"


# --- reading OFF answers ---
def test_only_complete_labels_are_kept():
    data = payload(
        ("Pełny", 100, 5, 3, 15), ("", 100, 5, 3, 15), ("Bez tłuszczu", 100, 5, None, 15)
    )
    data["products"].append({"product_name": "Bez składników"})
    data["products"].append({"product_name": "Śmieci", "nutriments": {"energy-kcal_100g": "abc"}})

    assert [p.name for p in parse_products(data)] == ["Pełny"]
    assert parse_products({}) == [] and parse_products({"products": None}) == []


def test_kilojoules_are_used_when_kilocalories_are_missing():
    data = {
        "products": [
            {
                "product_name": "Tylko kJ",
                "nutriments": {
                    "energy_100g": 1500,
                    "proteins_100g": "10",
                    "fat_100g": 1,
                    "carbohydrates_100g": 70,
                },
            }
        ]
    }

    only = parse_products(data)[0]

    assert only.kcal == pytest.approx(1500 / 4.184)  # 358.5
    assert only.protein == 10.0  # numbers given as strings are accepted


def test_products_sold_in_poland_are_recognised():
    data = payload(("A", 1, 0, 0, 0, ["en:poland", "en:germany"]), ("B", 1, 0, 0, 0, ["en:france"]))

    assert [p.in_poland for p in parse_products(data)] == [True, False]


# --- choosing the median ---
def test_the_estimate_is_the_median_of_the_matching_products():
    products = parse_products(payload(*FLOURS))

    result = estimate(entry(), products)

    # kcal 340 341 346 347 350 -> 346; protein 10 10 11 11.3 12 -> 11; fat 0.9 1 1.2 1.2 1.2 -> 1.2
    # carbs 70 71.7 72 72.5 74 -> 72
    assert (result.kcal, result.protein, result.fat, result.carbs) == (346.0, 11.0, 1.2, 72.0)
    assert result.products_used == 5


def test_one_odd_product_does_not_move_the_median():
    products = parse_products(payload(*FLOURS, ("Mąka pszenna z cukrem", 900, 0, 0, 5)))

    assert estimate(entry(), products).kcal == 346.0


def test_products_that_do_not_match_the_name_or_are_excluded_are_ignored():
    butter = entry("masło", exclude=("orzechowe", "kakaowe"))
    items = [(f"Masło ekstra {i}", 740 + i, 0.7, 82, 0.6) for i in range(5)]
    items += [("Masło orzechowe", 600, 25, 50, 15)] * 4  # peanut butter: excluded
    items += [("Margaryna", 500, 0, 56, 0)] * 4  # does not contain the word

    result = estimate(butter, parse_products(payload(*items)))

    assert result.products_used == 5 and result.kcal == 742.0


def test_all_words_of_the_query_must_appear():
    items = [(f"Mąka żytnia {i}", 330, 8, 1.5, 70) for i in range(6)]

    assert estimate(entry(), parse_products(payload(*items))) is None  # "pszenna" is missing


def test_implausible_labels_are_dropped():
    bad = [(f"Mąka pszenna zła {i}", 900, 90, 90, 90) for i in range(10)]

    assert estimate(entry(), parse_products(payload(*bad))) is None


def test_too_few_products_give_no_estimate():
    few = parse_products(payload(*FLOURS[: MIN_PRODUCTS - 1]))

    assert estimate(entry(), few) is None


def test_products_sold_in_poland_are_preferred_when_there_are_enough():
    polish = [(f"Mąka pszenna PL {i}", 340, 10, 1, 70, ["en:poland"]) for i in range(5)]
    foreign = [(f"Mąka pszenna DE {i}", 360, 12, 2, 75, ["en:germany"]) for i in range(8)]

    assert estimate(entry(), parse_products(payload(*polish, *foreign))).kcal == 340.0
    # with too few Polish products, everything is used
    assert estimate(entry(), parse_products(payload(*polish[:2], *foreign))).products_used == 10


# --- the polite client ---
def make_client(handler, *, sleeps=None, delay=6.5):
    return OffClient(
        delay_sec=delay,
        transport=httpx2.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_the_client_identifies_itself_and_asks_for_the_right_things():
    seen = {}

    def handler(request):
        seen["request"] = request
        return httpx2.Response(200, json=payload(*FLOURS))

    make_client(handler).search("mąka pszenna")

    request = seen["request"]
    assert request.headers["user-agent"] == get_settings().fetch_user_agent
    assert "RecipeMacrosBot" in request.headers["user-agent"]
    assert request.url.params["search_terms"] == "mąka pszenna"
    assert request.url.params["json"] == "1" and request.url.params["page_size"] == "60"
    assert "nutriments" in request.url.params["fields"]


def test_the_client_waits_between_requests_but_not_before_the_first():
    sleeps = []
    client = make_client(lambda r: httpx2.Response(200, json=payload()), sleeps=sleeps, delay=6.5)

    for query in ("a", "b", "c"):
        client.search(query)

    assert sleeps == [6.5, 6.5]


def test_a_busy_server_is_retried_with_growing_pauses():
    sleeps, calls = [], []

    def handler(request):
        calls.append(1)
        return (
            httpx2.Response(503) if len(calls) < 3 else httpx2.Response(200, json=payload(*FLOURS))
        )

    result = make_client(handler, sleeps=sleeps).search("mąka")

    assert len(parse_products(result)) == 5 and len(calls) == 3
    assert sleeps == [15.0, 30.0]  # no pause before the first request


def test_it_gives_up_after_three_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(503)

    with pytest.raises(OffError, match="503"):
        make_client(handler).search("mąka")

    assert len(calls) == 4  # the request and three retries


def test_network_errors_are_retried_then_reported():
    def handler(request):
        raise httpx2.ConnectError("down")

    with pytest.raises(OffError, match="not reachable"):
        make_client(handler).search("mąka")


@pytest.mark.parametrize(
    "response", [httpx2.Response(404), httpx2.Response(200, content=b"not json")]
)
def test_other_failures_are_reported_at_once_without_retrying(response):
    calls = []

    def handler(request):
        calls.append(1)
        return response

    with pytest.raises(OffError):
        make_client(handler).search("mąka")

    assert len(calls) == 1


# --- writing to the shared catalog ---
@pytest.fixture
def owner_engine():
    engine = create_engine(TEST_ADMIN_URL)
    yield engine
    engine.dispose()


def off_handler(answers):
    def handler(request):
        query = request.url.params["search_terms"]
        if isinstance(answers.get(query), int):
            return httpx2.Response(answers[query])
        return httpx2.Response(200, json=answers.get(query, payload()))

    return handler


def shared_rows(admin_db):
    rows = admin_db.execute(
        text(
            "SELECT canonical_name, kcal_per_100g, density_g_per_ml, source FROM ingredients "
            "WHERE user_id IS NULL ORDER BY canonical_name"
        )
    )
    return [(n, float(k), None if d is None else float(d), s) for n, k, d, s in rows]


def test_the_import_writes_shared_products_with_density_and_piece_weights(owner_engine, admin_db):
    entries = [
        entry("mąka pszenna", density=0.53),
        entry("jajko", query="jajka", piece_g=55),
        entry("sól", fixed=(0, 0, 0, 0), density=1.2),
    ]
    eggs = payload(*[(f"Jajka {i}", 139 + i, 12.5, 9.7, 0.6) for i in range(5)])
    client = make_client(off_handler({"mąka pszenna": payload(*FLOURS), "jajka": eggs}))

    outcomes = import_catalog(owner_engine, entries, client)

    assert [(o.name, o.status) for o in outcomes] == [
        ("mąka pszenna", "inserted"), ("jajko", "inserted"), ("sól", "inserted"),
    ]  # fmt: skip
    assert shared_rows(admin_db) == [
        ("jajko", 141.0, None, "off"),
        ("mąka pszenna", 346.0, 0.53, "off"),
        ("sól", 0.0, 1.2, "manual"),  # typed in, not from OFF
    ]
    egg_weight = admin_db.execute(
        text(
            "SELECT c.grams_per_unit, c.user_id FROM unit_conversions c "
            "JOIN ingredients i ON i.id = c.ingredient_id WHERE i.canonical_name = 'jajko'"
        )
    ).one()
    assert float(egg_weight[0]) == 55 and egg_weight[1] is None  # a shared conversion


def test_running_it_again_updates_instead_of_duplicating(owner_engine, admin_db):
    client = make_client(off_handler({"mąka pszenna": payload(*FLOURS)}))
    import_catalog(owner_engine, [entry(density=0.53, piece_g=None)], client)

    again = import_catalog(owner_engine, [entry(density=None)], client)  # density not repeated

    assert [o.status for o in again] == ["updated"]
    assert shared_rows(admin_db) == [("mąka pszenna", 346.0, 0.53, "off")]  # density kept


def test_a_failing_ingredient_does_not_stop_the_others(owner_engine, admin_db):
    entries = [entry("mąka pszenna"), entry("kasza", query="kasza"), entry("ryż", query="ryż")]
    rice = payload(*[(f"Ryż biały {i}", 345, 7.4, 0.7, 77) for i in range(6)])
    client = make_client(
        off_handler({"mąka pszenna": 404, "kasza": payload(("Kasza", 350, 10, 1, 70)), "ryż": rice})
    )

    outcomes = import_catalog(owner_engine, entries, client)

    assert [o.status for o in outcomes] == ["failed", "skipped", "inserted"]
    assert "too few" in outcomes[1].detail
    assert [r[0] for r in shared_rows(admin_db)] == ["ryż"]


def test_dry_run_writes_nothing(owner_engine, admin_db):
    client = make_client(off_handler({"mąka pszenna": payload(*FLOURS)}))

    outcomes = import_catalog(owner_engine, [entry()], client, dry_run=True)

    assert outcomes[0].status == "would_write" and outcomes[0].estimate.kcal == 346.0
    assert shared_rows(admin_db) == []


def test_fixed_entries_need_no_off_client(owner_engine, admin_db):
    outcomes = import_catalog(owner_engine, [entry("woda", fixed=(0, 0, 0, 0), density=1.0)], None)

    assert outcomes[0].status == "inserted" and shared_rows(admin_db) == [
        ("woda", 0.0, 1.0, "manual")
    ]
    with pytest.raises(ValueError, match="OFF client is required"):
        import_catalog(owner_engine, [entry()], None)


def test_the_applications_restricted_role_cannot_write_the_shared_catalog(admin_db):
    client = make_client(off_handler({"mąka pszenna": payload(*FLOURS)}))

    outcomes = import_catalog(app_engine, [entry()], client)  # connects as app_user

    assert outcomes[0].status == "failed" and "database error" in outcomes[0].detail
    assert shared_rows(admin_db) == []


# --- the point of it all: a recipe uses the imported catalog ---
def test_a_recipe_is_computed_from_the_imported_catalog(alice, owner_engine, admin_db):
    eggs = payload(*[(f"Jajka {i}", 140, 12.5, 9.7, 0.6) for i in range(5)])
    client = make_client(off_handler({"jajka": eggs}))
    import_catalog(owner_engine, [entry("jajko", query="jajka", piece_g=55)], client)
    egg_id = alice.get("/ingredients", params={"q": "jajko"}).json()["items"][0]["id"]
    recipe = recipe_with(alice, [line("3 jajka", qty=3, unit="piece", product_id=egg_id)])

    result = nutrition(alice, recipe)

    # 3 x 55 g = 165 g; 140 kcal/100 g -> 231 kcal. Measured data: nothing is an AI guess.
    assert result["total"]["kcal"] == 231.0 and result["measured_share"] == 1.0
    assert result["lines"][0]["is_estimate"] is False
