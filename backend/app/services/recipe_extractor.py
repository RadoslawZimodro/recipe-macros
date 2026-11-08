"""Extract a schema.org/Recipe from an HTML page's structured data (no AI involved).

Two formats are read: JSON-LD blocks and, as a fallback when those hold no usable recipe,
Microdata (see microdata.py, which converts it to the same dictionary shape). JSON-LD wins
when both are present: sites that carry both publish the same recipe twice.

Real-world data is messy, so this module is deliberately forgiving about SHAPE (a flat
object, a list, an @graph; @type as a string or a list; instructions as text, steps or
sections; images as URLs or objects) and strict about RESULT: everything is cleaned,
truncated to the limits of RecipeIn and validated before it is returned.

Ingredient lines are kept as text only (`raw_text`); splitting them into quantity, unit and
product is the job of the AI step.
"""

import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.schemas.recipe import IngredientLineIn, RecipeIn, StepIn
from app.services.microdata import microdata_recipe_nodes

MAX_NODES = 5000  # a hostile page cannot make us walk an endless JSON tree
MAX_DEPTH = 10
MAX_TAGS = 20
MAX_STEPS = 100
MAX_INGREDIENTS = 200

_LD_JSON = re.compile(r"^\s*application/ld\+json", re.IGNORECASE)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SPACES = re.compile(r"[ \t\r\f\v ​]+")
_STEP_NUMBER = re.compile(r"^\s*(?:krok|step)?\s*\d{1,2}\s*[.):]\s+", re.IGNORECASE)
_DURATION = re.compile(
    r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:[.,]\d+)?)S)?)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedRecipe:
    recipe: RecipeIn
    source_nutrition: dict[str, Any] | None
    method: str  # "jsonld" | "microdata": stored as the recipe's import_method
    # Picture address per step, parallel to recipe.steps (empty = the page had none).
    step_images: tuple[str | None, ...] = ()


# --- text helpers ---
def _clean_lines(value: Any) -> list[str]:
    """Plain-text lines from a JSON-LD value (HTML tags and entities removed)."""
    if isinstance(value, dict):
        value = value.get("text") or value.get("name") or value.get("@value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return []
    text = _BR.sub("\n", value)
    text = BeautifulSoup(text, "lxml").get_text("\n") if "<" in text else html.unescape(text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


def _one_line(value: Any) -> str | None:
    lines = _clean_lines(value)
    return " ".join(lines) if lines else None


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


# --- field parsers ---
def _types(node: dict) -> list[str]:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    # "https://schema.org/Recipe", "schema:Recipe" and "Recipe" are all the same type.
    return [
        str(v).rsplit("/", 1)[-1].rsplit(":", 1)[-1].lower() for v in values if isinstance(v, str)
    ]


def _servings(value: Any) -> int:
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, bool):
            continue
        match = re.search(r"\d+", str(item)) if item is not None else None
        if match:
            return max(1, min(int(match.group()), 1000))
    return 1


def _minutes(value: Any) -> int | None:
    """ISO 8601 duration (PT1H30M, P0DT45M, ...) as whole minutes; None if absent or invalid."""
    if not isinstance(value, str):
        return None
    match = _DURATION.match(value.strip())
    if not match:
        return None
    weeks, days, hours, minutes, seconds = (
        float(g.replace(",", ".")) if g else 0.0 for g in match.groups()
    )
    total = round(weeks * 10080 + days * 1440 + hours * 60 + minutes + seconds / 60)
    return total if 0 < total <= 100_000 else None


def _image_url(value: Any, base_url: str) -> str | None:
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, dict):
            item = item.get("url") or item.get("contentUrl") or item.get("@id")
        if not isinstance(item, str) or not item.strip():
            continue
        candidate = urljoin(base_url, item.strip())
        if candidate.lower().startswith(("http://", "https://")) and len(candidate) <= 2048:
            return candidate
    return None


def _collect_steps(value: Any, out: list[tuple[str, Any]], depth: int = 0) -> None:
    """Append (text, raw image value) per step line; only a HowToStep can carry an image."""
    if depth > MAX_DEPTH or len(out) >= MAX_STEPS:
        return
    if isinstance(value, str):
        out.extend((line, None) for line in _clean_lines(value))
    elif isinstance(value, list):
        for item in value:
            _collect_steps(item, out, depth + 1)
    elif isinstance(value, dict):
        if "howtosection" in _types(value) or (
            "itemListElement" in value and not value.get("text")
        ):
            _collect_steps(value.get("itemListElement"), out, depth + 1)
        else:  # HowToStep: prefer its text, fall back to its name
            lines = _clean_lines(value.get("text") or value.get("name"))
            # A picture belongs to the step as a whole: with several lines it is ambiguous.
            image = value.get("image") if len(lines) == 1 else None
            out.extend((line, image) for line in lines)


def _steps(value: Any, base_url: str) -> tuple[list[StepIn], list[str | None]]:
    """The steps and, in the same order, the address of each step's picture (or None)."""
    pairs: list[tuple[str, Any]] = []
    _collect_steps(value, pairs)
    steps: list[str] = []
    images: list[str | None] = []
    for line, image in pairs:
        line = _STEP_NUMBER.sub("", line).strip()
        if line and (not steps or steps[-1] != line):
            steps.append(line[:5000])
            images.append(_image_url(image, base_url) if image else None)
    return [StepIn(instruction=s) for s in steps[:MAX_STEPS]], images[:MAX_STEPS]


def _is_section_header(line: str) -> bool:
    """'Ciasto:' or 'Składniki na sos:' groups the lines below it; it is not an ingredient."""
    return line.endswith(":") and len(line) <= 60 and not any(ch.isdigit() for ch in line)


def _ingredients(node: dict) -> list[IngredientLineIn]:
    raw = node.get("recipeIngredient")
    if raw is None:
        raw = node.get("ingredients")  # legacy property name
    items = raw if isinstance(raw, list) else [raw]
    lines = [text for item in items if (text := _one_line(item))]
    lines = [line for line in lines if not _is_section_header(line)]
    return [IngredientLineIn(raw_text=line[:500]) for line in lines[:MAX_INGREDIENTS]]


def _tags(node: dict) -> list[str]:
    tags: list[str] = []
    for key in ("recipeCategory", "recipeCuisine", "keywords"):
        raw = node.get(key)
        for item in raw if isinstance(raw, list) else [raw]:
            text = _one_line(item)
            if text:
                tags.extend(re.split(r"[,;]", text))
    cleaned = (_SPACES.sub(" ", t).strip().lower() for t in tags)
    unique = dict.fromkeys(t for t in cleaned if t and len(t) <= 50)
    return list(unique)[:MAX_TAGS]


def _nutrition(value: Any) -> dict[str, Any] | None:
    """Keep the simple values (calories: '250 kcal', ...) the site published, nothing nested."""
    if not isinstance(value, dict):
        return None
    kept: dict[str, Any] = {}
    for key, item in value.items():
        if key.startswith("@") or len(key) > 50 or isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) or (isinstance(item, str) and len(item) <= 100):
            kept[key] = item
        if len(kept) >= 30:
            break
    return kept or None


# --- finding the Recipe node ---
def _load_json(raw: str) -> Any | None:
    text = raw.strip().lstrip("﻿")
    text = re.sub(r"^(?://\s*)?<!\[CDATA\[|(?://\s*)?\]\]>$", "", text).strip()
    text = re.sub(r"^<!--|-->$", "", text).strip()
    try:
        return json.loads(text, strict=False)  # strict=False tolerates raw newlines in strings
    except ValueError:
        return None


def _walk(node: Any, depth: int = 0, budget: list[int] | None = None) -> Iterator[dict]:
    budget = budget if budget is not None else [MAX_NODES]
    if depth > MAX_DEPTH or budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _walk(value, depth + 1, budget)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, depth + 1, budget)


def _recipe_nodes(soup: BeautifulSoup) -> Iterator[dict]:
    for script in soup.find_all("script", attrs={"type": _LD_JSON}):
        data = _load_json(script.string or script.get_text())
        if data is None:
            continue
        for node in _walk(data):
            if "recipe" in _types(node):
                yield node


def _build(node: dict, base_url: str, source_url: str, method: str) -> ExtractedRecipe | None:
    title = _one_line(_first(node.get("name")))
    steps, step_images = _steps(node.get("recipeInstructions"), base_url)
    ingredients = _ingredients(node)
    if not title or not (steps or ingredients):
        return None  # a bare teaser (name only) is not a usable recipe

    try:
        recipe = RecipeIn(
            title=title[:300],
            description=(_one_line(node.get("description")) or "")[:5000] or None,
            source_url=source_url,
            image_url=_image_url(node.get("image"), base_url),
            servings=_servings(node.get("recipeYield")),
            prep_time_min=_minutes(node.get("prepTime")),
            cook_time_min=_minutes(node.get("cookTime")),
            tags=_tags(node),
            steps=steps,
            ingredients=ingredients,
        )
    except ValidationError:
        return None
    return ExtractedRecipe(
        recipe=recipe,
        source_nutrition=_nutrition(node.get("nutrition")),
        method=method,
        step_images=tuple(step_images) if any(step_images) else (),
    )


def _fullest(nodes: Iterator[dict], base_url: str, source_url: str, method: str):
    built = (_build(node, base_url, source_url, method) for node in nodes)
    usable = [c for c in built if c is not None]
    # Pages sometimes carry a short teaser next to the full recipe: take the fuller one.
    return max(usable, key=lambda c: len(c.recipe.steps) + len(c.recipe.ingredients), default=None)


def extract_recipe(html_bytes: bytes, *, base_url: str, source_url: str) -> ExtractedRecipe | None:
    """The most complete schema.org Recipe on the page, or None if there is none.

    `base_url` is the final address of the page (relative image links are resolved against
    it); `source_url` is the normalized address that is stored with the recipe.
    """
    soup = BeautifulSoup(html_bytes, "lxml")
    found = _fullest(_recipe_nodes(soup), base_url, source_url, "jsonld")
    if found is None:  # Microdata is only read when JSON-LD gave nothing usable
        found = _fullest(microdata_recipe_nodes(soup), base_url, source_url, "microdata")
    return found
