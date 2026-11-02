"""Filling the shared product catalog from Open Food Facts (OFF).

OFF is an open database of packaged food, built from labels. It has brands, not "flour": a search
for "mąka pszenna" returns dozens of different products. A catalog entry is therefore the MEDIAN of
the matching products, which ignores a few odd ones (a flour mix, a mislabelled entry).

The data comes from OFF (https://world.openfoodfacts.org), made available under the Open Database
License (ODbL): the source must be named wherever the data is shown (see the README).
"""

import csv
import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx2

from app.config import get_settings
from app.services.products import ProductCandidate, plausible_macros

logger = logging.getLogger(__name__)

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "base_ingredients.csv"
SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
MIN_PRODUCTS = 5  # fewer matching products than this and the median means little
KJ_PER_KCAL = 4.184
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_PAUSES = (15.0, 30.0, 60.0)  # seconds to wait before the 1st, 2nd and 3rd retry


class OffError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    """One line of the starter list."""

    name: str  # the catalog name (lower case, singular)
    off_query: str
    exclude: tuple[str, ...]  # words that disqualify an OFF product ("orzechowe" for butter)
    density: float | None  # g per ml
    piece_g: float | None
    clove_g: float | None
    slice_g: float | None
    fixed: tuple[float, float, float, float] | None  # kcal, protein, fat, carbs typed in


@dataclass(frozen=True)
class OffProduct:
    name: str
    kcal: float
    protein: float
    fat: float
    carbs: float
    in_poland: bool


@dataclass(frozen=True)
class Estimate:
    kcal: float
    protein: float
    fat: float
    carbs: float
    products_used: int


# --- the starter list ---
def _number(value: str) -> float | None:
    value = value.strip().replace(",", ".")
    return float(value) if value else None


def load_entries(path: Path = DATA_FILE) -> list[Entry]:
    entries = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            if None in row or None in row.values():
                raise ValueError(f"{path.name} line {line_number}: wrong number of columns")
            macros = [_number(row[k]) for k in ("kcal", "protein", "fat", "carbs")]
            if any(v is not None for v in macros) and any(v is None for v in macros):
                raise ValueError(f"{path.name} line {line_number}: give all four values or none")
            entries.append(
                Entry(
                    name=row["name"].strip(),
                    off_query=row["off_query"].strip(),
                    exclude=tuple(w for w in row["exclude"].split(";") if w),
                    density=_number(row["density_g_per_ml"]),
                    piece_g=_number(row["piece_g"]),
                    clove_g=_number(row["clove_g"]),
                    slice_g=_number(row["slice_g"]),
                    fixed=tuple(macros) if macros[0] is not None else None,  # type: ignore[arg-type]
                )
            )
    return entries


# --- reading OFF answers ---
def _float(value) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def parse_products(payload: dict) -> list[OffProduct]:
    """The products of a search answer that have a name and a complete nutrition label."""
    products = []
    for item in payload.get("products") or []:
        nutriments = item.get("nutriments") or {}
        kcal = _float(nutriments.get("energy-kcal_100g"))
        if kcal is None:  # some entries only have kilojoules
            kilojoules = _float(nutriments.get("energy_100g"))
            kcal = None if kilojoules is None else kilojoules / KJ_PER_KCAL
        protein = _float(nutriments.get("proteins_100g"))
        fat = _float(nutriments.get("fat_100g"))
        carbs = _float(nutriments.get("carbohydrates_100g"))
        name = (item.get("product_name") or "").strip()
        if not name or None in (kcal, protein, fat, carbs):
            continue
        products.append(
            OffProduct(
                name,
                kcal,  # type: ignore[arg-type]
                protein,  # type: ignore[arg-type]
                fat,  # type: ignore[arg-type]
                carbs,  # type: ignore[arg-type]
                "en:poland" in (item.get("countries_tags") or []),
            )
        )
    return products


def estimate(entry: Entry, products: list[OffProduct]) -> Estimate | None:
    """The median label of the OFF products that really are `entry`, or None if too few are."""
    wanted = entry.off_query.casefold().split()
    excluded = [w.casefold() for w in entry.exclude]
    usable = []
    for product in products:
        name = product.name.casefold()
        if not all(word in name for word in wanted):
            continue
        if any(word in name for word in excluded):
            continue
        candidate = ProductCandidate(
            product.name, product.kcal, product.protein, product.fat, product.carbs
        )
        if plausible_macros(candidate):
            usable.append(product)

    polish = [p for p in usable if p.in_poland]
    chosen = polish if len(polish) >= MIN_PRODUCTS else usable  # prefer products sold in Poland
    if len(chosen) < MIN_PRODUCTS:
        return None
    return Estimate(
        kcal=round(statistics.median(p.kcal for p in chosen), 1),
        protein=round(statistics.median(p.protein for p in chosen), 1),
        fat=round(statistics.median(p.fat for p in chosen), 1),
        carbs=round(statistics.median(p.carbs for p in chosen), 1),
        products_used=len(chosen),
    )


# --- talking to OFF ---
class OffClient:
    """A polite client: identifies itself, waits between requests (OFF limits searches to about
    ten a minute) and never hammers the server."""

    def __init__(
        self,
        *,
        delay_sec: float = 6.5,
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._delay = delay_sec
        self._sleep = sleep
        self._last: float | None = None
        self._client = httpx2.Client(
            transport=transport,
            timeout=30,
            trust_env=False,
            follow_redirects=True,
            headers={"User-Agent": get_settings().fetch_user_agent},
        )

    def search(self, query: str) -> dict:
        """One search. A busy server (429, 5xx) is retried after a growing pause, three times."""
        if self._last is not None:
            self._sleep(self._delay)
        self._last = time.monotonic()
        params = {
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 60,
            "fields": "product_name,nutriments,countries_tags",
        }
        for attempt in range(len(RETRY_PAUSES) + 1):
            try:
                response = self._client.get(SEARCH_URL, params=params)
                if response.status_code in RETRY_STATUSES and attempt < len(RETRY_PAUSES):
                    logger.info("OFF answered %s, retrying", response.status_code)
                    self._sleep(RETRY_PAUSES[attempt])
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx2.TimeoutException, httpx2.TransportError) as exc:
                if attempt < len(RETRY_PAUSES):
                    self._sleep(RETRY_PAUSES[attempt])
                    continue
                raise OffError(f"Open Food Facts is not reachable: {exc}") from None
            except (httpx2.HTTPError, ValueError) as exc:
                raise OffError(f"Open Food Facts request failed: {exc}") from None
        raise OffError("Open Food Facts request failed")  # pragma: no cover

    def close(self) -> None:
        self._client.close()
