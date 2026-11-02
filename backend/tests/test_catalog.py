"""The starter list of the shared catalog and the writing of its products."""

import pytest
from sqlalchemy import create_engine, text

from app.db import engine as app_engine
from app.services.catalog import DATA_FILE, Entry, Estimate, load_entries, write_product
from app.services.products import normalize_name, plausible_density, plausible_unit_weight
from tests.conftest import TEST_ADMIN_URL


def entry(name="mąka pszenna", **kw):
    defaults = dict(
        name=name, density=None, piece_g=None, clove_g=None, slice_g=None, fixed=None
    )  # fmt: skip
    return Entry(**{**defaults, **kw})


@pytest.fixture
def owner_engine():
    engine = create_engine(TEST_ADMIN_URL)
    yield engine
    engine.dispose()


# --- the starter list is data too: it is checked ---
def test_the_starter_list_is_well_formed():
    entries = load_entries()

    assert len(entries) >= 50
    names = [e.name for e in entries]
    assert len({n.casefold() for n in names}) == len(names), "duplicate names"
    for e in entries:
        assert e.name == normalize_name(e.name), f"{e.name!r} is not in normalized form"
        assert e.density is None or plausible_density(e.density), e.name
        for unit, grams in (("piece", e.piece_g), ("clove", e.clove_g), ("slice", e.slice_g)):
            assert grams is None or plausible_unit_weight(unit, grams), (e.name, unit)


def test_the_list_contains_the_basics_with_sensible_numbers():
    by_name = {e.name: e for e in load_entries()}

    assert by_name["jajko"].piece_g == 55 and by_name["czosnek"].clove_g == 5
    assert by_name["miód"].density == 1.42 and by_name["mąka pszenna"].density == 0.53
    assert by_name["woda"].fixed == (0, 0, 0, 0) and by_name["sól"].fixed == (0, 0, 0, 0)


def test_a_malformed_list_is_refused(tmp_path):
    header = "name,density_g_per_ml,piece_g,clove_g,slice_g,kcal,protein,fat,carbs\n"
    short = tmp_path / "short.csv"
    short.write_text(header + "mąka,0.5\n", encoding="utf-8")
    partial = tmp_path / "partial.csv"
    partial.write_text(header + "sól,1.2,,,,0,0,,\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wrong number of columns"):
        load_entries(short)
    with pytest.raises(ValueError, match="all four values or none"):
        load_entries(partial)


def test_data_file_is_inside_the_package():
    assert DATA_FILE.exists() and DATA_FILE.suffix == ".csv"


# --- writing to the shared catalog ---
def shared_rows(admin_db):
    rows = admin_db.execute(
        text(
            "SELECT canonical_name, kcal_per_100g, density_g_per_ml, source FROM ingredients "
            "WHERE user_id IS NULL ORDER BY canonical_name"
        )
    )
    return [(n, float(k), None if d is None else float(d), s) for n, k, d, s in rows]


def test_a_product_is_written_with_its_density_and_piece_weight(owner_engine, admin_db):
    values = Estimate(140, 12.5, 9.7, 0.6, products_used=1)

    inserted = write_product(owner_engine, entry("jajko", piece_g=55), values, "usda")

    assert inserted is True
    assert shared_rows(admin_db) == [("jajko", 140.0, None, "usda")]
    grams = admin_db.execute(
        text(
            "SELECT grams_per_unit FROM unit_conversions WHERE unit_code = 'piece' "
            "AND user_id IS NULL"
        )
    ).scalar_one()
    assert float(grams) == 55.0


def test_writing_again_updates_instead_of_duplicating(owner_engine, admin_db):
    write_product(owner_engine, entry(), Estimate(340, 10, 1, 70, 1), "usda")

    inserted = write_product(owner_engine, entry(), Estimate(350, 11, 1, 71, 1), "usda")

    assert inserted is False
    assert shared_rows(admin_db) == [("mąka pszenna", 350.0, None, "usda")]


def test_the_applications_restricted_role_cannot_write_the_shared_catalog(admin_db):
    with pytest.raises(Exception):  # noqa: B017 - the database refuses, whatever the driver raises
        write_product(app_engine, entry(), Estimate(340, 10, 1, 70, 1), "usda")

    assert shared_rows(admin_db) == []
