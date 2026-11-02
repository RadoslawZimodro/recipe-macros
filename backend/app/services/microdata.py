"""schema.org Microdata (`itemscope` / `itemtype` / `itemprop` attributes in the HTML) read into
the same dictionary shape JSON-LD uses, so one mapping (recipe_extractor) serves both formats.

Many older sites, and several popular Polish food blogs, mark their recipes up this way.
The rules follow the HTML Microdata specification:

  * the properties of an item are the `itemprop` elements below it, EXCLUDING those that
    belong to a nested `itemscope` (so an author's `name` never overwrites the recipe's);
  * a property's value is a nested item (if the element is an `itemscope`), an attribute
    (`content` of <meta>, `href` of <a>/<link>, `src` of <img>, `datetime` of <time>, ...)
    or, for any other element, its text;
  * `itemref` pulls in properties that live elsewhere in the document.
"""

from collections.abc import Iterator
from typing import Any

from bs4 import BeautifulSoup, Tag

MAX_ELEMENTS = 100_000  # a hostile page cannot make us walk an endless document
MAX_DEPTH = 10  # nesting of items (a recipe inside a review inside ...)

# Elements that start a new line in the rendered text; their boundaries separate list items
# and paragraphs, while inline elements (<b>, <span>, <a>) do not split a sentence.
_BLOCK_TAGS = [
    *("p", "div", "li", "ul", "ol", "dl", "dt", "dd", "tr", "table", "section", "article"),
    *("aside", "header", "footer", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6"),
]
_URL_ATTRIBUTE = {
    "a": "href",
    "area": "href",
    "link": "href",
    "img": "src",
    "audio": "src",
    "video": "src",
    "source": "src",
    "embed": "src",
    "iframe": "src",
    "track": "src",
    "object": "data",
}


def _is_recipe_type(itemtype: str | None) -> bool:
    # "https://schema.org/Recipe", "http://schema.org/Recipe/" and several types in one attribute
    return any(token.rstrip("/").lower().endswith("/recipe") for token in (itemtype or "").split())


def _prepare_text(soup: BeautifulSoup) -> None:
    """Turn block boundaries and <br> into newlines once, so get_text() keeps list items and
    paragraphs apart without splitting sentences at inline tags."""
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")


def _property_value(element: Tag, root: BeautifulSoup, depth: int, budget: list[int]) -> Any:
    if element.has_attr("itemscope"):
        return _item_to_dict(element, root, depth + 1, budget)
    name = element.name
    if name == "meta":
        return element.get("content", "")
    if name in _URL_ATTRIBUTE:
        return element.get(_URL_ATTRIBUTE[name], "")
    if name in ("data", "meter"):
        return element.get("value", "")
    if name == "time":
        return element.get("datetime") or element.get_text()
    return element.get_text()


def _item_to_dict(item: Tag, root: BeautifulSoup, depth: int, budget: list[int]) -> dict[str, Any]:
    node: dict[str, Any] = {}
    if types := (item.get("itemtype") or "").split():
        node["@type"] = types
    if depth > MAX_DEPTH:
        return node

    start: list[Any] = list(item.children)
    for ref_id in (item.get("itemref") or "").split():  # properties defined elsewhere
        if (referenced := root.find(id=ref_id)) is not None:
            start.append(referenced)

    properties: dict[str, list[Any]] = {}
    stack = [child for child in reversed(start) if isinstance(child, Tag)]
    while stack and budget[0] > 0:
        element = stack.pop()
        budget[0] -= 1
        if names := element.get("itemprop"):
            value = _property_value(element, root, depth, budget)
            for property_name in str(names).split():
                properties.setdefault(property_name, []).append(value)
        # A nested item owns everything below it. Any other element (including one that is
        # itself a property) may still contain more properties of THIS item.
        if not element.has_attr("itemscope"):
            stack.extend(c for c in reversed(list(element.children)) if isinstance(c, Tag))

    for property_name, values in properties.items():
        node[property_name] = values[0] if len(values) == 1 else values
    return node


def microdata_recipe_nodes(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    """Every Recipe item on the page as a JSON-LD-shaped dictionary."""
    recipes = [
        el for el in soup.find_all(attrs={"itemscope": True}) if _is_recipe_type(el.get("itemtype"))
    ]
    if not recipes:
        return
    _prepare_text(soup)
    budget = [MAX_ELEMENTS]
    for element in recipes:
        yield _item_to_dict(element, soup, 0, budget)
