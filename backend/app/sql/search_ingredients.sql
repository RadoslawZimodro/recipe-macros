-- Products visible to the user: the shared catalog plus their own (RLS policy ingredients_read).
-- Same search idea as list_recipes.sql: substring via ILIKE, typos via pg_trgm, best match first.
SELECT
    g.id,
    g.canonical_name,
    g.kcal_per_100g,
    g.protein_per_100g,
    g.fat_per_100g,
    g.carbs_per_100g,
    g.density_g_per_ml,
    g.source,
    (g.user_id IS NULL) AS is_shared
FROM ingredients g
WHERE CAST(:q AS text) IS NULL
   OR g.canonical_name ILIKE :pattern
   OR g.canonical_name % CAST(:q AS text)
ORDER BY
    CASE WHEN CAST(:q AS text) IS NULL THEN NULL ELSE similarity(g.canonical_name, CAST(:q AS text)) END
        DESC NULLS LAST,
    g.canonical_name,
    g.id
LIMIT :limit OFFSET :offset
