"""USDA FoodData Central: download the two datasets and load a raw copy into the staging tables.

Foundation Foods (about 400 foods, the newest measurements) and SR Legacy (about 7800 foods,
frozen since 2018, with the weights of household measures) come as ZIP files of CSV tables.
Only what the project needs is kept: the foods of those two datasets, their energy, protein, fat
and carbohydrate, and their portions (what a cup or a piece weighs). The CSV is read straight out
of the ZIP (nothing is extracted to disk) and written with COPY, which is far faster than INSERTs.
The USDA data is in the public domain (CC0).
"""

import csv
import io
import logging
import urllib.request
import zipfile
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import Engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://fdc.nal.usda.gov/fdc-datasets/"
# Pinned on purpose. The Foundation release of 2026-10-29 is published without food.csv,
# food_nutrient.csv and food_portion.csv, so the last complete release is used.
FOUNDATION_ZIP = "FoodData_Central_foundation_food_csv_2025-12-18.zip"
SR_LEGACY_ZIP = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"

MAX_ZIP_BYTES = 50 * 1024 * 1024
TIMEOUT_SEC = 120

DATA_TYPES = ("foundation_food", "sr_legacy_food")
# Protein, fat, carbohydrate (by difference), energy (kcal) and the two Atwater energy values
# that Foundation Foods carries instead of 1008.
NUTRIENT_IDS = frozenset({1003, 1004, 1005, 1008, 2047, 2048})


class UsdaError(Exception):
    """A readable failure: the download or a file did not look as expected."""


def download(name: str, directory: Path) -> Path:
    """Fetch one dataset ZIP into `directory` (a fresh, empty folder), with a size limit."""
    target = directory / name
    request = urllib.request.Request(
        DOWNLOAD_URL + name, headers={"User-Agent": get_settings().fetch_user_agent}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            data = response.read(MAX_ZIP_BYTES + 1)
    except OSError as exc:
        raise UsdaError(f"could not download {name}: {exc}") from exc
    if len(data) > MAX_ZIP_BYTES:
        raise UsdaError(f"{name} is larger than {MAX_ZIP_BYTES // 1024 // 1024} MB, giving up")
    target.write_bytes(data)
    return target


def read_table(zip_path: Path, table: str) -> Iterator[dict[str, str]]:
    """Rows of `<table>.csv` inside the ZIP (the files sit in a sub-folder, so match by name)."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UsdaError(f"{zip_path.name} is not a readable ZIP file") from exc
    with archive:
        members = [m for m in archive.namelist() if m.rsplit("/", 1)[-1] == f"{table}.csv"]
        if len(members) != 1:
            raise UsdaError(f"{zip_path.name} should contain exactly one {table}.csv")
        with archive.open(members[0]) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def _int(value: str) -> int | None:
    return int(value) if value.strip().isdigit() else None


def _decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def collect(zip_paths: list[Path]) -> dict[str, list[tuple]]:
    """Read the ZIPs and return the rows of the four staging tables, nothing is written yet."""
    foods: dict[int, tuple] = {}
    nutrients: dict[tuple[int, int], tuple] = {}
    portions: dict[int, tuple] = {}
    units: dict[int, tuple] = {}

    for path in zip_paths:
        for row in read_table(path, "food"):
            if row["data_type"] in DATA_TYPES and row["description"].strip():
                foods[int(row["fdc_id"])] = (
                    int(row["fdc_id"]), row["data_type"], row["description"].strip()
                )  # fmt: skip
        for row in read_table(path, "measure_unit"):
            units[int(row["id"])] = (int(row["id"]), row["name"])

    for path in zip_paths:
        for row in read_table(path, "food_nutrient"):
            fdc_id, nutrient_id = _int(row["fdc_id"]), _int(row["nutrient_id"])
            amount = _decimal(row["amount"])
            if fdc_id in foods and nutrient_id in NUTRIENT_IDS and amount is not None:
                nutrients.setdefault((fdc_id, nutrient_id), (fdc_id, nutrient_id, amount))
        for row in read_table(path, "food_portion"):
            # Foundation has a few hundred portions without any food: they cannot be linked.
            fdc_id, grams = _int(row["fdc_id"]), _decimal(row["gram_weight"])
            if fdc_id not in foods or grams is None or grams <= 0:
                continue
            portions[int(row["id"])] = (
                int(row["id"]),
                fdc_id,
                _decimal(row["amount"]),
                _int(row["measure_unit_id"]),
                row["portion_description"].strip(),
                row["modifier"].strip(),
                grams,
            )
    return {
        "usda_food": list(foods.values()),
        "usda_food_nutrient": list(nutrients.values()),
        "usda_measure_unit": list(units.values()),
        "usda_food_portion": list(portions.values()),
    }


_COLUMNS = {
    "usda_food": "fdc_id, data_type, description",
    "usda_food_nutrient": "fdc_id, nutrient_id, amount",
    "usda_measure_unit": "id, name",
    "usda_food_portion": (
        "id, fdc_id, amount, measure_unit_id, portion_description, modifier, gram_weight"
    ),
}


def load_staging(engine: Engine, tables: dict[str, list[tuple]]) -> dict[str, int]:
    """Replace the staging tables with `tables` in ONE transaction: a failure keeps the old data.
    TRUNCATE + COPY makes running it again safe (the staging tables are a snapshot)."""
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE usda_food_portion, usda_measure_unit, usda_food_nutrient, usda_food")
        )
        cursor = conn.connection.driver_connection.cursor()
        # Parents before children: the foreign keys are checked as the rows arrive.
        for table in ("usda_food", "usda_measure_unit", "usda_food_nutrient", "usda_food_portion"):
            with cursor.copy(f"COPY {table} ({_COLUMNS[table]}) FROM STDIN") as copy:
                for row in tables[table]:
                    copy.write_row(row)
    return {table: len(rows) for table, rows in tables.items()}
