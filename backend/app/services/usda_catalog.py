"""Fill the shared catalog from the USDA staging tables, through the curated name mapping.

`usda_mapping.csv` says which USDA food stands for each of our (Polish) catalog names. The
nutrition comes from the staging tables (see app/services/usda.py), the density and piece weights
from the starter list, because USDA has no density and its portion weights vary per food.
A name without a mapping is skipped and reported; it is never guessed.
"""

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from app.services.catalog import Entry, Estimate, Outcome, write_product
from app.services.sql import load_sql

logger = logging.getLogger(__name__)

MAPPING_FILE = Path(__file__).resolve().parent.parent / "data" / "usda_mapping.csv"

# The limits of the CHECK constraint on ingredients (macros_range).
_MAX_KCAL = 900


@dataclass(frozen=True)
class Mapping:
    fdc_id: int
    note: str


def load_mapping(path: Path = MAPPING_FILE) -> dict[str, Mapping]:
    """name -> USDA food. A repeated name or an id that is not a number is an error."""
    mapping: dict[str, Mapping] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            name = (row.get("name") or "").strip()
            if not name or not (row.get("fdc_id") or "").strip().isdigit():
                raise ValueError(
                    f"{path.name} line {line_number}: need a name and a numeric fdc_id"
                )
            if name in mapping:
                raise ValueError(f"{path.name} line {line_number}: {name!r} is mapped twice")
            mapping[name] = Mapping(int(row["fdc_id"]), (row.get("note") or "").strip())
    return mapping


def _estimate(row) -> Estimate | None:
    """The row as per-100 g values, or None when a value is missing or impossible. Carbohydrate
    is computed by difference in USDA, so measurement noise can make it slightly negative (-0.4):
    that is a zero, not a reason to drop the food."""
    if None in (row.kcal, row.protein, row.fat, row.carbs):
        return None
    kcal, protein, fat, carbs = (
        round(float(value), 2) for value in (row.kcal, row.protein, row.fat, max(row.carbs, 0))
    )
    if not (0 <= kcal <= _MAX_KCAL and 0 <= protein <= 100 and 0 <= fat <= 100 and carbs <= 100):
        return None
    return Estimate(kcal, protein, fat, carbs, products_used=1)


def import_usda_catalog(
    engine: Engine,
    entries: list[Entry],
    mapping: dict[str, Mapping],
    *,
    dry_run: bool = False,
    on_outcome: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    """One outcome per entry. Values already in the catalog
    are replaced by the USDA ones; entries that cannot be filled from USDA are left untouched."""
    outcomes: list[Outcome] = []

    def add(outcome: Outcome) -> None:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    wanted = [mapping[e.name].fdc_id for e in entries if e.name in mapping]
    with engine.connect() as conn:
        found = {
            r.fdc_id: r for r in conn.execute(load_sql("usda_macros_by_id.sql"), {"ids": wanted})
        }

    for entry in entries:
        if entry.fixed is not None:  # water, salt: typed in
            values, source = Estimate(*entry.fixed, products_used=0), "manual"
        elif entry.name not in mapping:
            add(Outcome(entry.name, "skipped", "no USDA mapping"))
            continue
        else:
            row = found.get(mapping[entry.name].fdc_id)
            if row is None:
                add(Outcome(entry.name, "failed", "mapped USDA food is not in the staging tables"))
                continue
            values = _estimate(row)
            if values is None:
                add(Outcome(entry.name, "skipped", f"USDA values incomplete: {row.description}"))
                continue
            source = "usda"

        if dry_run:
            add(Outcome(entry.name, "would_write", estimate=values))
            continue
        try:
            inserted = write_product(engine, entry, values, source)
        except Exception as exc:  # the database refused: report it, carry on with the rest
            logger.exception("Writing %s failed", entry.name)
            add(Outcome(entry.name, "failed", f"database error: {exc.__class__.__name__}"))
            continue
        add(Outcome(entry.name, "inserted" if inserted else "updated", estimate=values))
    return outcomes


def staging_is_empty(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.exec_driver_sql("SELECT NOT EXISTS (SELECT 1 FROM usda_food)").scalar_one()
