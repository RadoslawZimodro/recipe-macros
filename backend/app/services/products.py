"""Link the products the AI named to the catalog, creating private estimates for new ones.

Matching rule (decided with the author): the exact name first, then a very similar one. Anything
else becomes a new PRIVATE product with source = 'llm_estimate'. The shared catalog is never
written by the AI.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.sql import load_sql

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class ProductCandidate:
    name: str
    kcal: float | None
    protein: float | None
    fat: float | None
    carbs: float | None


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


def resolve_products(
    session: Session, user_id: int, candidates: list[ProductCandidate]
) -> dict[str, int]:
    """Map normalized product name -> ingredient id. Names that could be neither matched nor
    created (implausible macros) are left out, so their recipe lines stay unlinked."""
    by_name: dict[str, ProductCandidate] = {}
    for candidate in candidates:
        # the first candidate with believable macros per name wins
        name = normalize_name(candidate.name)
        if name and (name not in by_name or not plausible_macros(by_name[name])):
            by_name[name] = candidate
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
            },
        ).scalar()
        if created is None:  # lost a race: the product exists now, use it
            created = session.execute(
                load_sql("match_products.sql"), {"names": [name], "min_similarity": 1.0}
            ).scalar()
        if created is not None:
            resolved[name] = created
    return resolved
