"""Write the starter list into the shared catalog (products and their conversions)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine

from app.services.off import Entry, Estimate, OffClient, OffError, estimate, parse_products
from app.services.sql import load_sql

logger = logging.getLogger(__name__)

# Stop after this many consecutive failures of OFF itself: it is down or blocking us, and
# waiting through the retries for every remaining ingredient would take hours.
MAX_CONSECUTIVE_OFF_FAILURES = 4

_PIECE_UNITS = (("piece", "piece_g"), ("clove", "clove_g"), ("slice", "slice_g"))


@dataclass(frozen=True)
class Outcome:
    name: str
    status: str  # inserted | updated | would_write | skipped | failed | aborted
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
    engine: Engine,
    entries: list[Entry],
    client: OffClient | None,
    *,
    dry_run: bool = False,
    on_outcome: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    """One outcome per entry (reported to `on_outcome` as soon as it is known). A failure of one
    entry never stops the others, except when OFF itself keeps failing: then the rest is aborted."""
    outcomes: list[Outcome] = []
    off_failures = 0

    def add(outcome: Outcome) -> None:
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)

    for index, entry in enumerate(entries):
        if off_failures >= MAX_CONSECUTIVE_OFF_FAILURES:
            for rest in entries[index:]:
                add(Outcome(rest.name, "aborted", "Open Food Facts did not answer, stopped early"))
            break
        if entry.fixed is not None:  # water, salt: typed in, OFF would add nothing
            values, source = Estimate(*entry.fixed, products_used=0), "manual"
        else:
            if client is None:
                raise ValueError("an OFF client is required for entries without fixed values")
            try:
                values = estimate(entry, _products(client, entry))
            except OffError as exc:
                off_failures += 1
                add(Outcome(entry.name, "failed", str(exc)))
                continue
            off_failures = 0
            if values is None:
                add(Outcome(entry.name, "skipped", "too few matching OFF products"))
                continue
            source = "off"

        if dry_run:
            add(Outcome(entry.name, "would_write", estimate=values))
            continue
        try:
            inserted = _write(engine, entry, values, source)
        except Exception as exc:  # the database refused: report it, carry on with the rest
            logger.exception("Writing %s failed", entry.name)
            add(Outcome(entry.name, "failed", f"database error: {exc.__class__.__name__}"))
            continue
        add(Outcome(entry.name, "inserted" if inserted else "updated", estimate=values))
    return outcomes


def _products(client: OffClient, entry: Entry):
    return parse_products(client.search(entry.off_query))
