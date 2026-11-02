"""Link the products the AI named to the catalog, creating private estimates for new ones.

Matching rule: the exact name first, then a very similar one; among equals the user's own manual
product wins, then a shared (measured) one, then the user's own AI estimate. Anything that does not
match becomes a new PRIVATE product with source = 'llm_estimate'. The shared catalog is never
written by the AI.

The AI also estimates what a spoon or a piece of the product weighs. Those numbers are stored as
the user's own conversions (unit_conversions), and only where no value is known yet, so an estimate
never overrides measured or curated data.
"""

import logging
import re
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.sql import load_sql

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"\s+")
COUNT_UNITS = ("piece", "clove", "slice", "pinch")


@dataclass(frozen=True)
class ProductCandidate:
    name: str
    kcal: float | None
    protein: float | None
    fat: float | None
    carbs: float | None
    density: float | None = None  # grams per millilitre
    unit_weights: tuple[tuple[str, float], ...] = ()  # (count unit, grams of ONE such unit)


def normalize_name(name: str | None) -> str | None:
    """Lower case, single spaces, no trailing punctuation; None if nothing useful is left."""
    if not name:
        return None
    cleaned = _SPACES.sub(" ", name).strip().strip(".,;:()").strip().lower()
    return cleaned[:200] or None


def plausible_macros(candidate: ProductCandidate) -> bool:
    """Is this a believable nutrition label for 100 g? Rejects obviously broken AI numbers.

    Values must be present and in range, the three macronutrients cannot exceed 100 g together,
    and the calories must roughly agree with 4 kcal/g protein and carbohydrates plus 9 kcal/g
    fat (the margin is wide on purpose: alcohol, fibre and polyols legitimately differ).
    """
    values = (candidate.kcal, candidate.protein, candidate.fat, candidate.carbs)
    if any(v is None for v in values):
        return False
    kcal, protein, fat, carbs = values  # type: ignore[misc]
    if not (0 <= kcal <= 900 and all(0 <= v <= 100 for v in (protein, fat, carbs))):
        return False
    if protein + fat + carbs > 100.5:
        return False
    estimate = 4 * protein + 4 * carbs + 9 * fat
    return abs(kcal - estimate) <= max(80.0, 0.4 * estimate)


def plausible_density(value: float | None) -> bool:
    """Between a fluffy powder (~0.1 g/ml) and a dense syrup (~1.5); anything beyond is an error."""
    return value is not None and 0.05 <= value <= 3.0


def plausible_unit_weight(unit: str, grams: float | None) -> bool:
    return unit in COUNT_UNITS and grams is not None and 0.05 <= grams <= 3000


def _merge(candidates: list[ProductCandidate]) -> dict[str, ProductCandidate]:
    """One candidate per normalized name: the first believable macros, the first density, and the
    unit weights of all the lines that mention the product."""
    merged: dict[str, ProductCandidate] = {}
    for candidate in candidates:
        name = normalize_name(candidate.name)
        if not name:
            continue
        current = merged.get(name)
        if current is None:
            merged[name] = replace(candidate, name=name)
            continue
        macros = current if plausible_macros(current) else candidate
        weights = dict(current.unit_weights)
        for unit, grams in candidate.unit_weights:
            weights.setdefault(unit, grams)
        merged[name] = ProductCandidate(
            name,
            macros.kcal,
            macros.protein,
            macros.fat,
            macros.carbs,
            current.density if current.density is not None else candidate.density,
            tuple(weights.items()),
        )
    return merged


def _existing_id(session: Session, name: str) -> int | None:
    """The id of the best visible product with exactly this name, if there is one."""
    row = (
        session.execute(load_sql("match_products.sql"), {"names": [name], "min_similarity": 1.0})
        .mappings()
        .first()
    )
    return None if row is None else row["id"]


def _store_conversions(
    session: Session, user_id: int, by_name: dict[str, ProductCandidate], ids: dict[str, int]
) -> None:
    triples: list[tuple[int, str, float]] = []
    for name, candidate in by_name.items():
        product_id = ids.get(name)
        if product_id is None:
            continue
        if plausible_density(candidate.density):
            triples.append((product_id, "ml", candidate.density))  # type: ignore[arg-type]
        triples.extend(
            (product_id, unit, grams)
            for unit, grams in candidate.unit_weights
            if plausible_unit_weight(unit, grams)
        )
    if triples:
        session.execute(
            load_sql("fill_conversions.sql"),
            {
                "user_id": user_id,
                "ids": [t[0] for t in triples],
                "units": [t[1] for t in triples],
                "grams": [t[2] for t in triples],
            },
        )


def resolve_products(
    session: Session, user_id: int, candidates: list[ProductCandidate]
) -> dict[str, int]:
    """Map normalized product name -> ingredient id. Names that could be neither matched nor
    created (implausible macros) are left out, so their recipe lines stay unlinked."""
    by_name = _merge(candidates)
    if not by_name:
        return {}

    min_similarity = get_settings().ai_product_match_similarity
    rows = session.execute(
        load_sql("match_products.sql"), {"names": list(by_name), "min_similarity": min_similarity}
    ).mappings()
    resolved: dict[str, int] = {}
    for row in rows:
        resolved[row["name"]] = row["id"]
        if not row["is_exact"]:
            logger.info(
                "ai_product_similar_match wanted=%r matched=%r", row["name"], row["canonical_name"]
            )

    for name, candidate in by_name.items():
        if name in resolved:
            continue
        if not plausible_macros(candidate):
            logger.info("ai_product_skipped name=%r reason=implausible_macros", name)
            continue
        created = session.execute(
            load_sql("insert_llm_product.sql"),
            {
                "user_id": user_id,
                "name": name,
                "kcal": round(candidate.kcal, 2),  # type: ignore[arg-type]
                "protein": round(candidate.protein, 2),  # type: ignore[arg-type]
                "fat": round(candidate.fat, 2),  # type: ignore[arg-type]
                "carbs": round(candidate.carbs, 2),  # type: ignore[arg-type]
                "density": round(candidate.density, 3)  # type: ignore[arg-type]
                if plausible_density(candidate.density)
                else None,
            },
        ).scalar()
        if created is None:  # lost a race: the product exists now, use it
            created = _existing_id(session, name)
        if created is not None:
            resolved[name] = created

    _store_conversions(session, user_id, by_name, resolved)
    return resolved
