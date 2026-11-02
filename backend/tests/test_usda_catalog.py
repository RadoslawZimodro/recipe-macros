"""Filling the shared catalog from the USDA staging tables through the curated mapping."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.services.catalog import DATA_FILE, load_entries
from app.services.usda import load_staging
from app.services.usda_catalog import (
    MAPPING_FILE,
    Mapping,
    import_usda_catalog,
    load_mapping,
    staging_is_empty,
)
from tests.conftest import TEST_ADMIN_URL
from tests.test_catalog import entry


@pytest.fixture
def owner_engine():
    engine = create_engine(TEST_ADMIN_URL)
    yield engine
    with engine.begin() as conn:  # leave the staging tables empty for the other tests
        conn.execute(
            text("TRUNCATE usda_food_portion, usda_measure_unit, usda_food_nutrient, usda_food")
        )
    engine.dispose()


@pytest.fixture
def staged(owner_engine):
    """Three USDA foods: a complete one, one with carbohydrate slightly below zero (as USDA's
    'by difference' can give) and one with only its energy."""

    def nutrients(fdc_id, kcal, protein, fat, carbs):
        return [
            (fdc_id, nutrient, Decimal(str(value)))
            for nutrient, value in ((1008, kcal), (1003, protein), (1004, fat), (1005, carbs))
            if value is not None
        ]

    load_staging(
        owner_engine,
        {
            "usda_food": [
                (1, "sr_legacy_food", "Wheat flour"),
                (2, "foundation_food", "Spinach, raw"),
                (3, "sr_legacy_food", "Mystery food"),
            ],
            "usda_food_nutrient": [
                *nutrients(1, 364, 10.33, 0.98, 76.31),
                *nutrients(2, 23, 2.9, 0.4, -0.4),
                *nutrients(3, 100, None, None, None),
            ],
            "usda_measure_unit": [],
            "usda_food_portion": [],
        },
    )


MAPPING = {
    "mąka pszenna": Mapping(1, ""),
    "szpinak": Mapping(2, ""),
    "tajemnica": Mapping(3, ""),
    "brakujące": Mapping(999, ""),
}


def shared_products(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT canonical_name, kcal_per_100g, carbs_per_100g, density_g_per_ml, source "
                "FROM ingredients WHERE user_id IS NULL ORDER BY canonical_name"
            )
        )
        return {r.canonical_name: r for r in rows}


def add_shared_product(owner_engine, name, kcal, protein, fat, carbs, source):
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ingredients (canonical_name, kcal_per_100g, protein_per_100g, "
                "fat_per_100g, carbs_per_100g, source) "
                "VALUES (:name, :kcal, :protein, :fat, :carbs, :source)"
            ),
            dict(name=name, kcal=kcal, protein=protein, fat=fat, carbs=carbs, source=source),
        )


def statuses(outcomes):
    return {o.name: o.status for o in outcomes}


def test_the_shipped_mapping_matches_the_starter_list():
    names = {e.name for e in load_entries(DATA_FILE)}
    mapping = load_mapping(MAPPING_FILE)

    assert set(mapping) <= names  # no line for an ingredient the list does not have
    assert len({m.fdc_id for m in mapping.values()}) == len(mapping)  # no food used twice


def test_mapping_file_errors_are_readable(tmp_path):
    bad_id = tmp_path / "bad.csv"
    bad_id.write_text("name,fdc_id,note\nmąka,abc,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2: need a name and a numeric fdc_id"):
        load_mapping(bad_id)

    twice = tmp_path / "twice.csv"
    twice.write_text("name,fdc_id,note\nmąka,1,\nmąka,2,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 3: 'mąka' is mapped twice"):
        load_mapping(twice)


def test_the_catalog_is_filled_with_usda_values(owner_engine, staged):
    entries = [entry("mąka pszenna", density=0.53), entry("szpinak")]

    outcomes = import_usda_catalog(owner_engine, entries, MAPPING)

    assert statuses(outcomes) == {"mąka pszenna": "inserted", "szpinak": "inserted"}
    products = shared_products(owner_engine)
    flour = products["mąka pszenna"]
    assert (flour.kcal_per_100g, flour.source) == (Decimal("364.00"), "usda")
    assert flour.density_g_per_ml == Decimal("0.530")  # the density comes from the starter list
    assert products["szpinak"].carbs_per_100g == 0  # -0.4 is a measurement noise, not a negative


def test_usda_replaces_values_that_were_already_in_the_catalog(owner_engine, staged):
    add_shared_product(owner_engine, "mąka pszenna", 340, 9, 1, 70, "off")

    outcomes = import_usda_catalog(owner_engine, [entry("mąka pszenna")], MAPPING)

    assert statuses(outcomes) == {"mąka pszenna": "updated"}
    flour = shared_products(owner_engine)["mąka pszenna"]
    assert (flour.kcal_per_100g, flour.source) == (Decimal("364.00"), "usda")


def test_what_usda_cannot_fill_is_skipped_and_left_alone(owner_engine, staged):
    add_shared_product(owner_engine, "twaróg", 133, 18, 4, 3, "off")
    entries = [entry("twaróg"), entry("tajemnica"), entry("brakujące")]

    outcomes = import_usda_catalog(owner_engine, entries, MAPPING)

    assert statuses(outcomes) == {
        "twaróg": "skipped",
        "tajemnica": "skipped",
        "brakujące": "failed",
    }
    assert "incomplete" in next(o.detail for o in outcomes if o.name == "tajemnica")
    products = shared_products(owner_engine)
    assert products["twaróg"].source == "off"  # not touched
    assert "tajemnica" not in products


def test_typed_in_entries_are_written_as_manual(owner_engine, staged):
    outcomes = import_usda_catalog(owner_engine, [entry("sól", fixed=(0, 0, 0, 0))], MAPPING)

    assert statuses(outcomes) == {"sól": "inserted"}
    assert shared_products(owner_engine)["sól"].source == "manual"


def test_dry_run_and_a_second_run(owner_engine, staged):
    entries = [entry("mąka pszenna")]

    dry = import_usda_catalog(owner_engine, entries, MAPPING, dry_run=True)
    assert statuses(dry) == {"mąka pszenna": "would_write"}
    assert shared_products(owner_engine) == {}

    import_usda_catalog(owner_engine, entries, MAPPING)
    again = import_usda_catalog(owner_engine, entries, MAPPING)
    assert statuses(again) == {"mąka pszenna": "updated"}  # updated, never duplicated
    assert len(shared_products(owner_engine)) == 1


def test_staging_is_empty_before_the_first_import(owner_engine):
    assert staging_is_empty(owner_engine)
