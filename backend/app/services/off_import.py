"""Write the starter list into the shared catalog (products and their conversions)."""

import logging
from dataclasses import dataclass

from sqlalchemy import Engine

from app.services.off import Entry, Estimate, OffClient, OffError, estimate, parse_products
from app.services.sql import load_sql

logger = logging.getLogger(__name__)

_PIECE_UNITS = (("piece", "piece_g"), ("clove", "clove_g"), ("slice", "slice_g"))


@dataclass(frozen=True)
class Outcome:
    name: str
    status: str  # inserted | updated | would_write | skipped | failed
    detail: str = ""
    estimate: Estimate | None = None


def _write(engine: Engine, entry: Entry, values: Estimate, source: str) -> bool:
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


def import_catalog(
    engine: Engine, entries: list[Entry], client: OffClient | None, *, dry_run: bool = False
) -> list[Outcome]:
    """One outcome per entry. A failure of one entry never stops the others."""
    outcomes = []
    for entry in entries:
        if entry.fixed is not None:  # water, salt: typed in, OFF would add nothing
            values, source = Estimate(*entry.fixed, products_used=0), "manual"
        else:
            if client is None:
                raise ValueError("an OFF client is required for entries without fixed values")
            try:
                values = estimate(entry, _products(client, entry))
            except OffError as exc:
                outcomes.append(Outcome(entry.name, "failed", str(exc)))
                continue
            if values is None:
                outcomes.append(Outcome(entry.name, "skipped", "too few matching OFF products"))
                continue
            source = "off"

        if dry_run:
            outcomes.append(Outcome(entry.name, "would_write", estimate=values))
            continue
        try:
            inserted = _write(engine, entry, values, source)
        except Exception as exc:  # the database refused: report it, carry on with the rest
            logger.exception("Writing %s failed", entry.name)
            outcomes.append(
                Outcome(entry.name, "failed", f"database error: {exc.__class__.__name__}")
            )
            continue
        outcomes.append(Outcome(entry.name, "inserted" if inserted else "updated", estimate=values))
    return outcomes


def _products(client: OffClient, entry: Entry):
    return parse_products(client.search(entry.off_query))
