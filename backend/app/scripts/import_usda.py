"""Load the USDA FoodData Central data into the staging tables (a raw copy, not the catalog).

    docker compose exec backend python -m app.scripts.import_usda
    docker compose exec backend python -m app.scripts.import_usda --sr-zip a.zip --foundation-zip b

It downloads Foundation Foods and SR Legacy (about 10 MB together), keeps the foods with their
energy, protein, fat, carbohydrate and portion weights, and replaces the usda_* tables with them
in one transaction. It is safe to run again. The shared catalog (`ingredients`) is NOT touched:
it receives only the products that are mapped to our names, in a separate step.
The data is in the public domain (CC0), source: https://fdc.nal.usda.gov
"""

import argparse
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import get_settings
from app.services.usda import (
    FOUNDATION_ZIP,
    SR_LEGACY_ZIP,
    UsdaError,
    collect,
    download,
    load_staging,
)

SUMMARY_SQL = text(
    """
    SELECT data_type,
           count(*)                                                         AS foods,
           count(*) FILTER (WHERE kcal IS NOT NULL AND protein IS NOT NULL
                              AND fat IS NOT NULL AND carbs IS NOT NULL)    AS with_all_macros
    FROM usda_food_macros
    GROUP BY data_type
    ORDER BY data_type
    """
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Load USDA FoodData Central into staging tables")
    parser.add_argument("--foundation-zip", help="use this Foundation Foods ZIP, do not download")
    parser.add_argument("--sr-zip", help="use this SR Legacy ZIP, do not download")
    args = parser.parse_args(argv[1:])

    settings = get_settings()
    # The staging tables belong to the database owner, not to the API's restricted role.
    engine = create_engine(settings.admin_database_url or settings.database_url)
    try:
        # A fresh temporary folder: downloaded files are never mixed with our own code.
        with tempfile.TemporaryDirectory(prefix="usda-") as folder:
            zips = [
                Path(args.foundation_zip) if args.foundation_zip else None,
                Path(args.sr_zip) if args.sr_zip else None,
            ]
            for index, name in enumerate((FOUNDATION_ZIP, SR_LEGACY_ZIP)):
                if zips[index] is None:
                    print(f"Downloading {name} ...", flush=True)
                    zips[index] = download(name, Path(folder))
            print("Reading the tables ...", flush=True)
            counts = load_staging(engine, collect([z for z in zips if z is not None]))
        with engine.connect() as conn:
            summary = conn.execute(SUMMARY_SQL).all()
    except UsdaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print("\nLoaded:", ", ".join(f"{n} {table}" for table, n in counts.items()))
    for row in summary:
        print(
            f"  {row.data_type:<16} {row.foods:>5} foods, {row.with_all_macros:>5} with all macros"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
