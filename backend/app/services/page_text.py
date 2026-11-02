"""Turn a recipe page into the plain text the AI reads (when the page has no structured data)."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.microdata import prepare_text

# Page furniture that is never part of a recipe.
_DROPPED_TAGS = [
    *("script", "style", "noscript", "template", "svg", "iframe", "form", "button", "select"),
    *("nav", "header", "footer", "aside"),
]
_INGREDIENTS_HEADING = re.compile(r"sk[łl]adniki|ingredients", re.IGNORECASE)
_BLANK_RUN = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t\r\f\v ​]+")


@dataclass(frozen=True)
class PageContent:
    text: str
    image_url: str | None
    truncated: bool


def _fit(text: str, limit: int) -> tuple[str, bool]:
    """Cut `text` to `limit` characters, keeping the part around the ingredients: blogs put a
    long story first, so cutting from the top could remove the recipe itself."""
    if len(text) <= limit:
        return text, False
    match = _INGREDIENTS_HEADING.search(text)
    start = max(0, match.start() - limit // 5) if match else 0
    return text[start : start + limit], True


def page_content(html: bytes, *, base_url: str, limit: int) -> PageContent:
    soup = BeautifulSoup(html, "lxml")

    image = None
    for prop in ("og:image", "twitter:image"):
        meta = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        content = meta.get("content") if meta else None
        if isinstance(content, str) and content.strip():
            candidate = urljoin(base_url, content.strip())
            if candidate.lower().startswith(("http://", "https://")) and len(candidate) <= 2048:
                image = candidate
                break

    for tag in soup.find_all(_DROPPED_TAGS):
        tag.decompose()
    prepare_text(soup)  # block elements and <br> become line breaks, inline tags do not
    body = soup.body or soup
    lines = (_SPACES.sub(" ", line).strip() for line in body.get_text().splitlines())
    text = _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()
    text, truncated = _fit(text, limit)
    return PageContent(text=text, image_url=image, truncated=truncated)
