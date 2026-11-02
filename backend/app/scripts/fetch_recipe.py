"""Try the import pipeline on a real address without saving anything.

    docker compose exec backend python -m app.scripts.fetch_recipe <url>

Fetches the page (same SSRF protection and robots.txt rules as the API, no cache), extracts
the schema.org recipe from its JSON-LD and prints it as JSON. Nothing is written to the
database and no page is stored, so third-party content never ends up in the repository.
"""

import json
import sys

from app.services.jsonld import extract_recipe
from app.services.page_fetcher import PageFetcher
from app.services.safe_fetch import FetchError
from app.services.urls import UrlError, normalize_url


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.scripts.fetch_recipe <url>", file=sys.stderr)
        return 2
    try:
        url = normalize_url(argv[1])
        page = PageFetcher().fetch(url)
    except (UrlError, FetchError) as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1

    extracted = extract_recipe(page.body, base_url=page.final_url, source_url=url)
    if extracted is None:
        print("error [no_recipe_data]: no schema.org Recipe found in JSON-LD", file=sys.stderr)
        return 1

    output = {
        "fetched": {"final_url": page.final_url, "bytes": len(page.body)},
        "recipe": extracted.recipe.model_dump(mode="json"),
        "source_nutrition": extracted.source_nutrition,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
