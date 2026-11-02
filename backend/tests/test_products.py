"""Linking AI-named products to the catalog, and creating private estimates for the rest."""

import pytest
from sqlalchemy import text

from app.db import SessionLocal, set_tenant
from app.services.products import (
    ProductCandidate,
    normalize_name,
    plausible_macros,
    resolve_products,
)
from tests.seed import conversion as seed_conversion
from tests.seed import product as seed_product
from tests.test_ingredients import FLOUR, add_shared


def cand(name, macros=(364, 10.3, 1.0, 76.3)):
    kcal, protein, fat, carbs = macros if macros else (None,) * 4
    return ProductCandidate(name, kcal, protein, fat, carbs)


@pytest.fixture
def as_alice(alice):
    """A session bound to Alice's tenant, like the one a request has."""
    with SessionLocal() as session:
        set_tenant(session, alice.user_id)
        yield session


def stored(admin_db, name, user_id=None):
    return admin_db.execute(
        text(
            "SELECT id, user_id, source, kcal_per_100g FROM ingredients "
            "WHERE lower(canonical_name) = :n AND user_id IS NOT DISTINCT FROM :u"
        ),
        {"n": name, "u": user_id},
    ).first()


# --- names ---
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mąka Pszenna", "mąka pszenna"),
        ("  oliwa   z\toliwek ", "oliwa z oliwek"),
        ("jajko.", "jajko"),
        ("(sól)", "sól"),
        ("x" * 300, "x" * 200),
        ("", None),
        ("   ", None),
        ("...", None),
        (None, None),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


# --- are the AI's numbers believable ---
@pytest.mark.parametrize(
    "macros",
    [
        (364, 10.3, 1.0, 76.3),  # flour
        (717, 0.9, 81.0, 0.1),  # butter
        (884, 0, 100, 0),  # oil: fat adds up to exactly 100 g
        (0, 0, 0, 0),  # salt, water
        (83, 0.1, 0, 2.6),  # wine: alcohol calories exceed the macronutrient estimate
        (247, 4.0, 1.2, 80.0),  # cinnamon: fibre lowers the real calories
    ],
)
def test_plausible_macros_are_accepted(macros):
    assert plausible_macros(cand("x", macros))


@pytest.mark.parametrize(
    "macros",
    [
        (None, 1, 1, 1),
        (100, None, 1, 1),
        (-1, 0, 0, 0),
        (901, 0, 0, 0),
        (100, 101, 0, 0),
        (100, 50, 50, 50),  # 150 g of nutrients in 100 g of product
        (500, 0, 0, 0),  # 500 kcal from nothing
        (0, 0, 0, 100),  # 100 g of carbohydrate cannot be 0 kcal
        (900, 0, 1, 1),
    ],
)
def test_implausible_macros_are_rejected(macros):
    assert not plausible_macros(cand("x", macros))


# --- matching ---
def test_exact_name_matches_a_shared_product(as_alice, admin_db):
    add_shared(admin_db, "mąka pszenna")
    shared_id = stored(admin_db, "mąka pszenna").id

    assert resolve_products(as_alice, 1, [cand("Mąka Pszenna")]) == {"mąka pszenna": shared_id}
    assert stored(admin_db, "mąka pszenna", None).id == shared_id  # nothing new was created


def test_exact_match_does_not_need_macros(as_alice, admin_db):
    add_shared(admin_db, "mąka pszenna")

    ids = resolve_products(as_alice, 1, [cand("mąka pszenna", macros=None)])

    assert "mąka pszenna" in ids


def test_own_product_shadows_a_shared_one_with_the_same_name(alice, as_alice, admin_db):
    add_shared(admin_db, "mąka pszenna")
    own = alice.post("/ingredients", json=FLOUR | {"canonical_name": "mąka pszenna"}).json()

    assert resolve_products(as_alice, alice.user_id, [cand("mąka pszenna")]) == {
        "mąka pszenna": own["id"]
    }


def test_another_users_private_product_is_never_matched(alice, bob, as_alice, admin_db):
    bob.post("/ingredients", json=FLOUR | {"canonical_name": "mąka pszenna"})

    ids = resolve_products(as_alice, alice.user_id, [cand("mąka pszenna")])
    as_alice.commit()

    created = stored(admin_db, "mąka pszenna", alice.user_id)
    assert created is not None and ids == {"mąka pszenna": created.id}  # Alice got her OWN new one


def test_a_very_similar_name_is_matched(as_alice, admin_db):
    add_shared(admin_db, "chicken breast")
    shared_id = stored(admin_db, "chicken breast").id

    assert resolve_products(as_alice, 1, [cand("chicken breasts")]) == {
        "chicken breasts": shared_id
    }


@pytest.mark.parametrize(
    ("existing", "wanted"),
    [
        ("mąka pszenna razowa", "mąka pszenna"),  # a different flour, 0.65
        ("masło orzechowe", "masło"),  # peanut butter is not butter
        ("mąka żytnia", "mąka pszenna"),
        ("mleko 3,2%", "mleko 2%"),  # similarity is exactly 0.80, but the digits differ
        ("mąka typ 450", "mąka typ 550"),
    ],
)
def test_similar_but_different_products_are_not_confused(as_alice, admin_db, existing, wanted):
    add_shared(admin_db, existing)
    existing_id = stored(admin_db, existing).id

    ids = resolve_products(as_alice, 1, [cand(wanted)])

    assert ids[wanted] != existing_id  # a new private product was made instead


def test_the_premise_of_the_digit_rule(admin_db):
    score = admin_db.execute(text("SELECT similarity('mleko 3,2%', 'mleko 2%')")).scalar_one()

    assert score >= 0.8  # without the digit rule these two WOULD be merged


# --- creating ---
def test_unknown_product_becomes_a_private_llm_estimate(alice, as_alice, admin_db):
    ids = resolve_products(as_alice, alice.user_id, [cand("Cynamon", (247, 4.0, 1.2, 80.0))])
    as_alice.commit()

    row = stored(admin_db, "cynamon", alice.user_id)
    assert ids == {"cynamon": row.id}
    assert row.source == "llm_estimate"  # marked as an estimate, never as measured data
    assert row.kcal_per_100g == 247


def test_the_second_import_reuses_the_product_it_created(alice, as_alice, admin_db):
    first = resolve_products(as_alice, alice.user_id, [cand("cynamon", (247, 4.0, 1.2, 80.0))])
    as_alice.commit()

    second = resolve_products(as_alice, alice.user_id, [cand("Cynamon", (999, 0, 0, 0))])

    assert second == first
    count = admin_db.execute(text("SELECT count(*) FROM ingredients")).scalar_one()
    assert count == 1


def test_implausible_macros_create_nothing_and_leave_the_line_unlinked(alice, as_alice, admin_db):
    ids = resolve_products(as_alice, alice.user_id, [cand("dziwny składnik", (900, 90, 90, 90))])

    assert ids == {}
    assert admin_db.execute(text("SELECT count(*) FROM ingredients")).scalar_one() == 0


def test_the_first_believable_candidate_per_name_wins(alice, as_alice, admin_db):
    candidates = [cand("cukier", (900, 90, 90, 90)), cand("Cukier", (400, 0, 0, 100))]

    ids = resolve_products(as_alice, alice.user_id, candidates)
    as_alice.commit()

    assert stored(admin_db, "cukier", alice.user_id).kcal_per_100g == 400
    assert list(ids) == ["cukier"]


def test_several_products_in_one_call(alice, as_alice, admin_db):
    add_shared(admin_db, "sól")
    candidates = [
        cand("sól"),
        cand("masło", (717, 0.9, 81, 0.1)),
        cand("jajko", (143, 12.6, 9.5, 0.7)),
    ]

    ids = resolve_products(as_alice, alice.user_id, candidates)

    assert set(ids) == {"sól", "masło", "jajko"} and len(set(ids.values())) == 3


def test_nothing_to_resolve(as_alice):
    assert resolve_products(as_alice, 1, []) == {}
    assert resolve_products(as_alice, 1, [cand("   ")]) == {}


# --- precedence: the user's manual entry, then measured data, then the user's AI estimate ---
def test_a_measured_shared_product_beats_the_users_old_ai_estimate(alice, as_alice, admin_db):
    seed_product(admin_db, "masło", 717, 0.9, 81, 0.1, user_id=alice.user_id, source="llm_estimate")
    shared = seed_product(admin_db, "masło", 717, 0.9, 81, 0.1)

    assert resolve_products(as_alice, alice.user_id, [cand("masło")]) == {"masło": shared}


def test_the_users_manual_product_beats_a_shared_one(alice, as_alice, admin_db):
    seed_product(admin_db, "masło", 717, 0.9, 81, 0.1)
    mine = seed_product(admin_db, "masło", 700, 1, 80, 1, user_id=alice.user_id, source="manual")

    assert resolve_products(as_alice, alice.user_id, [cand("masło")]) == {"masło": mine}


def test_the_users_ai_estimate_is_used_when_nothing_better_exists(alice, as_alice, admin_db):
    estimate = seed_product(
        admin_db, "masło", 717, 0.9, 81, 0.1, user_id=alice.user_id, source="llm_estimate"
    )

    assert resolve_products(as_alice, alice.user_id, [cand("masło")]) == {"masło": estimate}


def test_losing_a_creation_race_returns_the_id_of_the_winner_not_the_name(
    alice, as_alice, admin_db, monkeypatch
):
    # Another import creates "cynamon" between our lookup and our insert. The lookup is made to
    # miss once; the insert then conflicts, and the code must fetch the id of the existing row.
    winner = seed_product(
        admin_db, "cynamon", 247, 4, 1.2, 80, user_id=alice.user_id, source="llm_estimate"
    )
    from app.services import products as products_module

    real = products_module.load_sql
    calls = {"match": 0}

    def load(name):
        if name == "match_products.sql":
            calls["match"] += 1
            if calls["match"] == 1:  # the first lookup finds nothing
                return text(
                    "SELECT NULL::text AS name, NULL::int AS id, NULL::text AS canonical_name, "
                    "NULL::boolean AS is_exact WHERE false"
                )
        return real(name)

    monkeypatch.setattr(products_module, "load_sql", load)

    ids = resolve_products(as_alice, alice.user_id, [cand("cynamon", (247, 4.0, 1.2, 80.0))])

    assert ids == {"cynamon": winner}  # an int id, not the string "cynamon"


# --- what a spoon or a piece weighs ---
def stored_conversions(admin_db, user_id):
    rows = admin_db.execute(
        text(
            "SELECT i.canonical_name, c.unit_code, c.grams_per_unit, c.source "
            "FROM unit_conversions c JOIN ingredients i ON i.id = c.ingredient_id "
            "WHERE c.user_id = :u ORDER BY 1, 2"
        ),
        {"u": user_id},
    )
    return [(n, u, float(g), s) for n, u, g, s in rows]


def cand_w(name, *, density=None, weights=(), macros=(247, 4.0, 1.2, 80.0)):
    kcal, protein, fat, carbs = macros
    return ProductCandidate(name, kcal, protein, fat, carbs, density, tuple(weights))


def test_a_new_product_gets_its_density_and_piece_weight(alice, as_alice, admin_db):
    resolve_products(
        as_alice, alice.user_id, [cand_w("jajko", density=None, weights=[("piece", 55.0)])]
    )
    resolve_products(as_alice, alice.user_id, [cand_w("mleko", density=1.03)])
    as_alice.commit()

    assert stored_conversions(admin_db, alice.user_id) == [
        ("jajko", "piece", 55.0, "llm_estimate"),
    ]  # the density went into the product row itself
    density = admin_db.execute(
        text("SELECT density_g_per_ml FROM ingredients WHERE canonical_name = 'mleko'")
    ).scalar_one()
    assert float(density) == 1.03


def test_unit_weights_of_all_lines_of_a_product_are_merged(alice, as_alice, admin_db):
    resolve_products(
        as_alice,
        alice.user_id,
        [
            cand_w("czosnek", weights=[("clove", 5.0)]),
            cand_w("czosnek", weights=[("piece", 40.0), ("clove", 99.0)]),  # first value wins
        ],
    )
    as_alice.commit()

    assert stored_conversions(admin_db, alice.user_id) == [
        ("czosnek", "clove", 5.0, "llm_estimate"),
        ("czosnek", "piece", 40.0, "llm_estimate"),
    ]


def test_ai_estimates_never_override_what_is_already_known(alice, as_alice, admin_db):
    egg = seed_product(admin_db, "jajko", 143, 12.6, 9.5, 0.7)
    seed_conversion(admin_db, egg, "piece", 55)  # a curated shared weight
    flour = seed_product(admin_db, "mąka", 364, 10.3, 1, 76.3, density=0.53)  # density known
    onion = seed_product(admin_db, "cebula", 40, 1.1, 0.1, 9.3)  # nothing known

    resolve_products(
        as_alice,
        alice.user_id,
        [
            cand_w("jajko", weights=[("piece", 70.0)]),
            cand_w("mąka", density=0.9),
            cand_w("cebula", density=0.6, weights=[("piece", 110.0)]),
        ],
    )
    as_alice.commit()

    assert stored_conversions(admin_db, alice.user_id) == [
        ("cebula", "ml", 0.6, "llm_estimate"),
        ("cebula", "piece", 110.0, "llm_estimate"),
    ]  # only the gaps were filled: no second egg weight, no second flour density
    assert egg and flour and onion


def test_filling_conversions_twice_changes_nothing(alice, as_alice, admin_db):
    seed_product(admin_db, "cebula", 40, 1.1, 0.1, 9.3)
    for _ in range(2):
        resolve_products(as_alice, alice.user_id, [cand_w("cebula", weights=[("piece", 110.0)])])
        as_alice.commit()

    assert len(stored_conversions(admin_db, alice.user_id)) == 1


@pytest.mark.parametrize(
    ("density", "weights"),
    [
        (0.0, [("piece", 0.0)]),
        (50.0, [("piece", 5000.0)]),  # a piece of 5 kg, a density of 50 g/ml
        (-1.0, [("g", 10.0)]),  # a mass unit has no "weight per unit"
        (None, [("tbsp", 15.0)]),  # only count units carry a weight per unit
        (None, [("piece", None)]),
    ],
)
def test_implausible_conversions_are_ignored(alice, as_alice, admin_db, density, weights):
    seed_product(admin_db, "cebula", 40, 1.1, 0.1, 9.3)

    resolve_products(as_alice, alice.user_id, [cand_w("cebula", density=density, weights=weights)])
    as_alice.commit()

    assert stored_conversions(admin_db, alice.user_id) == []


def test_conversions_of_a_product_that_could_not_be_resolved_are_dropped(alice, as_alice, admin_db):
    broken = cand_w("dziwny", density=1.0, weights=[("piece", 10.0)], macros=(900, 90, 90, 90))

    assert resolve_products(as_alice, alice.user_id, [broken]) == {}
    as_alice.commit()

    assert stored_conversions(admin_db, alice.user_id) == []
