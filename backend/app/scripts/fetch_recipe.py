"""Try the import pipeline on a real address without saving anything.

    docker compose exec backend python -m app.scripts.fetch_recipe <url>        # page -> markup
    docker compose exec backend python -m app.scripts.fetch_recipe <url> --ai   # + the AI's reading

Fetches the page (same SSRF protection and robots.txt rules as the API, no page cache) and
extracts the schema.org recipe from its JSON-LD or Microdata. With --ai the AI is asked too and
its reading is printed line by line, so you can judge the quality of the AI import on real pages.
--ai calls the paid Anthropic API (answers are cached for a week, so repeating costs nothing).
Nothing is written to the database and no page is stored, so third-party content never ends up
in the repository.
"""

import json
import sys

from app.config import get_settings
from app.schemas.ai import AIRefinement
from app.services.ai_client import AIUnavailable, ClaudeClient
from app.services.ai_extract import AIInvalidOutput, NoRecipeOnPage, RecipeAI
from app.services.page_fetcher import PageFetcher
from app.services.page_text import page_content
from app.services.recipe_extractor import ExtractedRecipe, extract_recipe
from app.services.redis_client import get_redis
from app.services.safe_fetch import FetchedPage, FetchError
from app.services.urls import UrlError, normalize_url

CLI_USER_ID = 0  # the CLI has its own daily AI allowance


def _macros(item) -> str:
    values = (item.kcal_per_100g, item.protein_per_100g, item.fat_per_100g, item.carbs_per_100g)
    if any(v is None for v in values):
        return "no estimate"
    return "{:g} kcal  P{:g} F{:g} C{:g} per 100 g".format(*values)


def _print_ai(result: AIRefinement, raw_lines: list[str] | None) -> None:
    print("\n--- AI reading: ingredient lines ---")
    for item in sorted(result.ingredients, key=lambda i: i.line):
        raw = raw_lines[item.line] if raw_lines and item.line < len(raw_lines) else item.raw_text
        amount = " ".join(
            str(part)
            for part in (None if item.quantity is None else f"{item.quantity:g}", item.unit)
            if part
        )
        product = item.product_name or "(not a food)"
        print(f"{item.line:>3}  {raw[:46]:<46} -> {amount or '-':<10} {product}")
        print(f"       {_macros(item)}{'  [optional]' if item.is_optional else ''}")
    print(f"\n--- AI reading: {len(result.steps)} steps ---")
    for number, step in enumerate(result.steps, start=1):
        print(f"{number:>3}. {step[:110]}")


def _run_ai(page: FetchedPage, extracted: ExtractedRecipe | None) -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("error [ai_not_configured]: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1
    client = ClaudeClient(
        settings.anthropic_api_key,
        settings.ai_model,
        timeout=settings.ai_timeout_sec,
        max_output_tokens=settings.ai_max_output_tokens,
    )
    ai = RecipeAI(client, get_redis())
    try:
        if extracted is not None:
            recipe = extracted.recipe
            raw_lines = [line.raw_text for line in recipe.ingredients]
            print(f"\nMode: markup found ({extracted.method}); the AI takes the lines apart.")
            result = ai.refine(CLI_USER_ID, raw_lines, [s.instruction for s in recipe.steps])
            _print_ai(result, raw_lines)
        else:
            content = page_content(
                page.body, base_url=page.final_url, limit=settings.ai_max_page_chars
            )
            print(
                f"\nMode: no markup; the AI reads the page text ({len(content.text)} characters"
                f"{', truncated' if content.truncated else ''})."
            )
            full = ai.extract_page(CLI_USER_ID, content.text, page.final_url)
            print(f"Title: {full.title}")
            print(
                f"Servings: {full.servings}  prep: {full.prep_time_min}  cook: {full.cook_time_min}"
            )
            print(f"Tags: {full.tags}\nImage: {content.image_url}")
            _print_ai(full, None)
    except NoRecipeOnPage:
        print("The AI found no recipe on this page.", file=sys.stderr)
        return 1
    except AIUnavailable as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    except AIInvalidOutput as exc:
        print(f"error [ai_invalid_output]: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--ai"]
    use_ai = "--ai" in argv[1:]
    if len(args) != 1:
        print("usage: python -m app.scripts.fetch_recipe <url> [--ai]", file=sys.stderr)
        return 2
    try:
        url = normalize_url(args[0])
        page = PageFetcher().fetch(url)
    except (UrlError, FetchError) as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1

    extracted = extract_recipe(page.body, base_url=page.final_url, source_url=url)
    if extracted is None and not use_ai:
        print(
            "error [no_recipe_data]: no schema.org Recipe found in JSON-LD or Microdata (try --ai)",
            file=sys.stderr,
        )
        return 1

    if extracted is not None:
        output = {
            "fetched": {"final_url": page.final_url, "bytes": len(page.body)},
            "recipe": extracted.recipe.model_dump(mode="json"),
            "source_nutrition": extracted.source_nutrition,
            "step_images": list(extracted.step_images),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return _run_ai(page, extracted) if use_ai else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
