"""Fill the SHARED product catalog with measured data from Open Food Facts.

    docker compose exec backend python -m app.scripts.import_off --dry-run
    docker compose exec backend python -m app.scripts.import_off
    docker compose exec backend python -m app.scripts.import_off --only mąka

For every ingredient of app/data/base_ingredients.csv the script searches Open Food Facts,
takes the MEDIAN of the matching products' labels (calories, protein, fat, carbohydrates per 100 g)
and writes it to the shared catalog as source = 'off', together with the density and piece weights
from the list. It is safe to run again: rows are updated, not duplicated. Ingredients with too few
matching products are skipped and reported.

Open Food Facts asks clients to identify themselves and to stay under about ten searches a minute,
so the script waits between requests (the whole list takes several minutes).
The data is (c) Open Food Facts contributors, available under the Open Database License (ODbL).
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app.config import get_settings
from app.services.off import DATA_FILE, OffClient, load_entries
from app.services.off_import import import_catalog


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fill the shared catalog from Open Food Facts")
    parser.add_argument("--dry-run", action="store_true", help="show the numbers, write nothing")
    parser.add_argument("--only", help="only entries whose name contains this text")
    parser.add_argument("--delay", type=float, default=6.5, help="seconds between OFF requests")
    parser.add_argument("--list", default=str(DATA_FILE), help="path of the CSV with the list")
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
    client = OffClient(delay_sec=args.delay)
    print(
        f"{len(entries)} ingredients{' (dry run)' if args.dry_run else ''}; this can take a while"
    )
    try:
        outcomes = import_catalog(engine, entries, client, dry_run=args.dry_run)
    finally:
        client.close()

    for outcome in outcomes:
        values = outcome.estimate
        numbers = (
            f"{values.kcal:>6g} kcal  P{values.protein:<5g} F{values.fat:<5g} C{values.carbs:<5g}"
            f" (from {values.products_used} products)"
            if values and values.products_used
            else (f"{values.kcal:>6g} kcal  (typed in)" if values else outcome.detail)
        )
        print(f"{outcome.status:<11} {outcome.name:<26} {numbers}")
    counts = {s: sum(o.status == s for o in outcomes) for s in {o.status for o in outcomes}}
    print("\nSummary:", ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    return 0 if any(o.status in ("inserted", "updated", "would_write") for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
