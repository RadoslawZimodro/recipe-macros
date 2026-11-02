"""Fill the SHARED product catalog from the USDA data .

    docker compose exec backend python -m app.scripts.import_usda            # once: staging tables
    docker compose exec backend python -m app.scripts.import_usda_catalog --dry-run
    docker compose exec backend python -m app.scripts.import_usda_catalog
    docker compose exec backend python -m app.scripts.import_usda_catalog --only mąka

For every ingredient of app/data/starter_ingredients.csv that has a line in
app/data/usda_mapping.csv the script takes the macros per 100 g of the mapped USDA food and
writes them to the shared catalog as source = 'usda', together with the density and piece
weights from the list. Rows that are already there are updated, not duplicated; ingredients
without a mapping are left as they are and reported. Safe to run again.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app.config import get_settings
from app.services.catalog import DATA_FILE, Outcome, load_entries
from app.services.usda_catalog import (
    MAPPING_FILE,
    import_usda_catalog,
    load_mapping,
    staging_is_empty,
)


def _show(outcome: Outcome) -> None:
    values = outcome.estimate
    if values is not None:
        details = (
            f"{values.kcal:>6g} kcal  P{values.protein:<5g} F{values.fat:<5g} C{values.carbs:<5g}"
        )
    else:
        details = outcome.detail
    print(f"{outcome.status:<11} {outcome.name:<26} {details}", flush=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fill the shared catalog from USDA data")
    parser.add_argument("--dry-run", action="store_true", help="show the numbers, write nothing")
    parser.add_argument("--only", help="only entries whose name contains this text")
    parser.add_argument("--list", default=str(DATA_FILE), help="path of the CSV with the list")
    parser.add_argument("--mapping", default=str(MAPPING_FILE), help="path of the mapping CSV")
    args = parser.parse_args(argv[1:])

    entries = load_entries(Path(args.list))
    if args.only:
        entries = [e for e in entries if args.only.casefold() in e.name.casefold()]
    if not entries:
        print("No matching entries.", file=sys.stderr)
        return 2

    settings = get_settings()
    # Shared rows can only be written by the database owner, not by the API's restricted role.
    engine = create_engine(settings.admin_database_url or settings.database_url)
    try:
        if staging_is_empty(engine):
            print(
                "The USDA staging tables are empty. Run first: python -m app.scripts.import_usda",
                file=sys.stderr,
            )
            return 1
        outcomes = import_usda_catalog(
            engine,
            entries,
            load_mapping(Path(args.mapping)),
            dry_run=args.dry_run,
            on_outcome=_show,
        )
    finally:
        engine.dispose()

    counts = {s: sum(o.status == s for o in outcomes) for s in {o.status for o in outcomes}}
    print("\nSummary:", ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    return 0 if any(o.status in ("inserted", "updated", "would_write") for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
