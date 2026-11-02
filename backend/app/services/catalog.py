"""The starter list of the shared catalog and the writing of its products.

`starter_ingredients.csv` names the basic ingredients (lower case, singular) and holds what no
nutrition database has: the density and the weight of a piece, clove or slice. The macros come from
the USDA data (see usda_catalog.py); water and salt have them typed in.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from app.services.sql import load_sql

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "starter_ingredients.csv"

_PIECE_UNITS = (("piece", "piece_g"), ("clove", "clove_g"), ("slice", "slice_g"))


@dataclass(frozen=True)
class Entry:
    """One line of the starter list."""

    name: str  # the catalog name (lower case, singular)
    density: float | None  # g per ml
    piece_g: float | None
    clove_g: float | None
    slice_g: float | None
    fixed: tuple[float, float, float, float] | None  # kcal, protein, fat, carbs typed in


@dataclass(frozen=True)
class Estimate:
    """Macros per 100 g; `products_used` is how many source foods they rest on (0 = typed in)."""

    kcal: float
    protein: float
    fat: float
    carbs: float
    products_used: int


@dataclass(frozen=True)
class Outcome:
    name: str
    status: str  # inserted | updated | would_write | skipped | failed
    detail: str = ""
    estimate: Estimate | None = None


def _number(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    return float(value) if value else None


def load_entries(path: Path = DATA_FILE) -> list[Entry]:
    entries = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            if None in row or None in row.values():
                raise ValueError(f"{path.name} line {line_number}: wrong number of columns")
            macros = [_number(row[k]) for k in ("kcal", "protein", "fat", "carbs")]
            if any(v is not None for v in macros) and any(v is None for v in macros):
                raise ValueError(f"{path.name} line {line_number}: give all four values or none")
            entries.append(
                Entry(
                    name=row["name"].strip(),
                    density=_number(row["density_g_per_ml"]),
                    piece_g=_number(row["piece_g"]),
                    clove_g=_number(row["clove_g"]),
                    slice_g=_number(row["slice_g"]),
                    fixed=tuple(macros) if macros[0] is not None else None,  # type: ignore[arg-type]
                )
            )
    return entries


def write_product(engine: Engine, entry: Entry, values: Estimate, source: str) -> bool:
    """Upsert one product and its conversions in one transaction; True if it was inserted."""
    with engine.begin() as conn:
        row = conn.execute(
            load_sql("upsert_shared_product.sql"),
            {
                "name": entry.name,
                "kcal": values.kcal,
                "protein": values.protein,
                "fat": values.fat,
                "carbs": values.carbs,
                "density": entry.density,
                "source": source,
            },
        ).one()
        for unit, attribute in _PIECE_UNITS:
            grams = getattr(entry, attribute)
            if grams is not None:
                conn.execute(
                    load_sql("upsert_shared_conversion.sql"),
                    {"product_id": row.id, "unit": unit, "grams": grams},
                )
    return row.inserted
