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
so the script waits between requests (the whole list takes several minutes). If OFF keeps failing
the script stops early; run it again later, finished rows are simply updated.
The data is (c) Open Food Facts contributors, available under the Open Database License (ODbL).
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app.config import get_settings
from app.services.off import DATA_FILE, OffClient, load_entries
from app.services.off_import import Outcome, import_catalog


def _show(outcome: Outcome) -> None:
    """Print one result as soon as it is known (a full run takes minutes)."""
    values = outcome.estimate
    if values is not None and values.products_used:
        details = (
            f"{values.kcal:>6g} kcal  P{values.protein:<5g} F{values.fat:<5g} C{values.carbs:<5g}"
            f" (from {values.products_used} products)"
        )
    elif values is not None:
        details = f"{values.kcal:>6g} kcal  (typed in)"
    else:
        details = outcome.detail
    print(f"{outcome.status:<11} {outcome.name:<26} {details}", flush=True)


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
        f"{len(entries)} ingredients{' (dry run)' if args.dry_run else ''}; this can take a while",
        flush=True,
    )
    try:
        outcomes = import_catalog(engine, entries, client, dry_run=args.dry_run, on_outcome=_show)
    finally:
        client.close()

    counts = {
        status: sum(o.status == status for o in outcomes) for status in {o.status for o in outcomes}
    }
    print("\nSummary:", ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
    if counts.get("aborted"):
        print(
            "Open Food Facts kept failing, so the rest was skipped. Nothing is lost: run the "
            "script again later and it continues (finished rows are only updated)."
        )
    return 0 if any(o.status in ("inserted", "updated", "would_write") for o in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
