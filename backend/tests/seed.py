"""Helpers that put products and conversions straight into the database (as the owner role)."""

from sqlalchemy import text


def product(
    admin_db,
    name,
    kcal,
    protein,
    fat,
    carbs,
    *,
    density=None,
    user_id=None,
    source=None,
) -> int:
    """A product per 100 g. user_id None = shared catalog. source defaults to 'off' (shared) or
    'manual' (private)."""
    source = source or ("off" if user_id is None else "manual")
    product_id = admin_db.execute(
        text(
            "INSERT INTO ingredients (user_id, canonical_name, kcal_per_100g, protein_per_100g, "
            "fat_per_100g, carbs_per_100g, density_g_per_ml, source) "
            "VALUES (:u, :n, :k, :p, :f, :c, :d, :s) RETURNING id"
        ),
        {
            "u": user_id,
            "n": name,
            "k": kcal,
            "p": protein,
            "f": fat,
            "c": carbs,
            "d": density,
            "s": source,
        },
    ).scalar_one()
    admin_db.commit()
    return product_id


def conversion(admin_db, product_id, unit, grams, *, user_id=None, source="manual") -> None:
    """Grams per ONE unit of a product ('ml' = density). user_id None = shared."""
    admin_db.execute(
        text(
            "INSERT INTO unit_conversions "
            "(ingredient_id, user_id, unit_code, grams_per_unit, source) "
            "VALUES (:i, :u, :c, :g, :s)"
        ),
        {"i": product_id, "u": user_id, "c": unit, "g": grams, "s": source},
    )
    admin_db.commit()


def line(raw, *, qty=None, unit=None, product_id=None, optional=False, grams=None):
    """One ingredient line of a recipe payload."""
    data = {"raw_text": raw, "quantity": qty, "unit": unit, "ingredient_id": product_id}
    data["is_optional"] = optional
    if grams is not None:
        data["grams"] = grams
    return data
