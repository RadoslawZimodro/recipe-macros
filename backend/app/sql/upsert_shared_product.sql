-- A product of the SHARED catalog (user_id NULL). Run by the import script with the database
-- owner's rights: the application role cannot write shared rows (Row-Level Security).
-- Idempotent: running the script again refreshes the numbers. A density already in the table is
-- kept when the new run has none.
-- RETURNING: (xmax = 0) tells an inserted row from an updated one.
INSERT INTO ingredients (
    user_id, canonical_name, kcal_per_100g, protein_per_100g, fat_per_100g, carbs_per_100g,
    density_g_per_ml, source
)
VALUES (NULL, :name, :kcal, :protein, :fat, :carbs, :density, :source)
ON CONFLICT (lower(canonical_name)) WHERE user_id IS NULL
DO UPDATE SET
    kcal_per_100g    = EXCLUDED.kcal_per_100g,
    protein_per_100g = EXCLUDED.protein_per_100g,
    fat_per_100g     = EXCLUDED.fat_per_100g,
    carbs_per_100g   = EXCLUDED.carbs_per_100g,
    density_g_per_ml = COALESCE(EXCLUDED.density_g_per_ml, ingredients.density_g_per_ml),
    source           = EXCLUDED.source
RETURNING id, (xmax = 0) AS inserted
