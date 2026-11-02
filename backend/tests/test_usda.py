"""USDA import: reading the ZIPs, the staging load and the macros view.
No test touches the real USDA server: the ZIPs are built here, in the same shape as the real ones
(CSV files inside a sub-folder)."""

import zipfile
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.services.usda import UsdaError, collect, load_staging, read_table
from tests.conftest import TEST_ADMIN_URL

FOOD_HEADER = "fdc_id,data_type,description,food_category_id,publication_date"
NUTRIENT_HEADER = "id,fdc_id,nutrient_id,amount,data_points"
PORTION_HEADER = "id,fdc_id,seq_num,amount,measure_unit_id,portion_description,modifier,gram_weight"


def make_zip(tmp_path, name, files):
    """A ZIP like USDA's: every CSV sits in a folder named after the archive."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for table, lines in files.items():
            archive.writestr(f"{path.stem}/{table}.csv", "﻿" + "\n".join(lines) + "\n")
    return path


@pytest.fixture
def sr_zip(tmp_path):
    return make_zip(
        tmp_path,
        "sr.zip",
        {
            "food": [
                FOOD_HEADER,
                '1,sr_legacy_food,"Flour, wheat",1,2019-04-01',
                "2,sr_legacy_food,Butter,1,2019-04-01",
                "3,branded_food,Some branded biscuit,1,2019-04-01",  # not a dataset we keep
            ],
            "food_nutrient": [
                NUTRIENT_HEADER,
                "10,1,1008,364,1",
                "11,1,1003,10.33,1",
                "12,1,1004,0.98,1",
                "13,1,1005,76.31,1",
                "14,1,1079,2.7,1",  # fibre: not needed
                "15,2,1008,717,1",
                "16,3,1008,500,1",  # belongs to a food that is not kept
            ],
            "measure_unit": ["id,name", "1000,cup", "9999,undetermined"],
            "food_portion": [
                PORTION_HEADER,
                "100,1,1,1,9999,,cup,125",
                "101,1,2,1,9999,,tbsp,0",  # a weight of zero says nothing
                "102,3,1,1,9999,,slice,30",  # food not kept
            ],
        },
    )


@pytest.fixture
def foundation_zip(tmp_path):
    return make_zip(
        tmp_path,
        "foundation.zip",
        {
            "food": [
                FOOD_HEADER,
                "20,foundation_food,Oil olive,1,2025-12-18",
                "21,sample_food,OLIVE OIL sample,1,2019-04-01",  # lab sample: not kept
            ],
            "food_nutrient": [
                NUTRIENT_HEADER,
                "30,20,2047,884,1",  # no 1008: Foundation carries Atwater energy instead
                "31,20,2048,900,1",
                "32,20,1004,100,1",
                "33,20,1004,99,1",  # a repeated (food, nutrient): the first one wins
            ],
            "measure_unit": ["id,name", "1000,cup", "1001,tablespoon"],
            "food_portion": [
                PORTION_HEADER,
                "200,20,,1,1001,,,13.6",
                "201,,1,1,,,,30",  # an orphan portion without a food (present in the real file)
            ],
        },
    )


@pytest.fixture
def owner_engine():
    engine = create_engine(TEST_ADMIN_URL)
    yield engine
    with engine.begin() as conn:  # leave the staging tables empty for the other tests
        conn.execute(
            text("TRUNCATE usda_food_portion, usda_measure_unit, usda_food_nutrient, usda_food")
        )
    engine.dispose()


def test_read_table_finds_a_file_inside_the_archive_folder(sr_zip):
    rows = list(read_table(sr_zip, "food"))
    assert [r["fdc_id"] for r in rows] == ["1", "2", "3"]
    assert rows[0]["description"] == "Flour, wheat"  # the byte order mark did not leak into a key


def test_read_table_reports_a_missing_file(sr_zip):
    with pytest.raises(UsdaError, match=r"exactly one nothing\.csv"):
        list(read_table(sr_zip, "nothing"))


def test_read_table_reports_a_broken_archive(tmp_path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip")
    with pytest.raises(UsdaError, match="not a readable ZIP"):
        list(read_table(broken, "food"))


def test_collect_keeps_only_what_the_project_needs(sr_zip, foundation_zip):
    tables = collect([foundation_zip, sr_zip])

    assert sorted(f[0] for f in tables["usda_food"]) == [1, 2, 20]
    kept = {(fdc, nutrient) for fdc, nutrient, _ in tables["usda_food_nutrient"]}
    assert kept == {(1, 1008), (1, 1003), (1, 1004), (1, 1005), (2, 1008)} | {
        (20, 2047),
        (20, 2048),
        (20, 1004),
    }
    fat = next(a for fdc, n, a in tables["usda_food_nutrient"] if (fdc, n) == (20, 1004))
    assert fat == 100  # the repeated value did not replace the first
    assert sorted(p[0] for p in tables["usda_food_portion"]) == [100, 200]
    assert {u[0] for u in tables["usda_measure_unit"]} == {1000, 1001, 9999}


def test_load_staging_replaces_the_previous_snapshot(owner_engine, sr_zip, foundation_zip):
    counts = load_staging(owner_engine, collect([foundation_zip, sr_zip]))
    assert counts["usda_food"] == 3
    assert counts["usda_food_portion"] == 2

    counts = load_staging(owner_engine, collect([sr_zip]))  # run again with less data
    with owner_engine.connect() as conn:
        foods = conn.execute(text("SELECT count(*) FROM usda_food")).scalar_one()
    assert counts["usda_food"] == foods == 2


def test_failed_load_keeps_the_old_data(owner_engine, sr_zip):
    load_staging(owner_engine, collect([sr_zip]))
    bad = collect([sr_zip])
    bad["usda_food_portion"].append(bad["usda_food_portion"][0])  # the same primary key twice

    with pytest.raises(Exception, match="usda_food_portion"):
        load_staging(owner_engine, bad)
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM usda_food")).scalar_one() == 2


def test_macros_view_gives_one_row_per_food(owner_engine, sr_zip, foundation_zip):
    load_staging(owner_engine, collect([foundation_zip, sr_zip]))
    with owner_engine.connect() as conn:
        rows = {
            r.fdc_id: r
            for r in conn.execute(text("SELECT * FROM usda_food_macros ORDER BY fdc_id"))
        }

    flour, butter, oil = rows[1], rows[2], rows[20]
    assert (flour.kcal, flour.protein, flour.fat, flour.carbs) == (
        Decimal("364"),
        Decimal("10.33"),
        Decimal("0.98"),
        Decimal("76.31"),
    )
    assert butter.kcal == 717 and butter.protein is None  # missing stays NULL, not 0
    assert oil.kcal == 884  # no 1008, so Atwater general (2047) wins over specific (2048)
    assert oil.fat == 100


def test_usda_is_an_allowed_source_of_products_and_conversions(owner_engine):
    with owner_engine.begin() as conn:
        product_id = conn.execute(
            text(
                "INSERT INTO ingredients (canonical_name, kcal_per_100g, protein_per_100g, "
                "fat_per_100g, carbs_per_100g, source) VALUES ('mąka', 364, 10, 1, 76, 'usda') "
                "RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO unit_conversions (ingredient_id, unit_code, grams_per_unit, source) "
                "VALUES (:id, 'piece', 50, 'usda')"
            ),
            {"id": product_id},
        )


def test_staging_tables_are_closed_to_the_application_role(db):
    with pytest.raises(Exception, match="permission denied"):
        db.execute(text("SELECT * FROM usda_food")).all()
