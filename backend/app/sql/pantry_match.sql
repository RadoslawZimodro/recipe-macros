-- Which recipes can be cooked with what the user has, best match first.
--
-- A required ingredient line counts as "have" when its product has the same NAME (case
-- insensitive) as a product in the pantry, in the user's "always at home" list, or in the default
-- list (water, salt, pepper). Matching by name rather than by id means the user's own "mąka" and
-- the catalog's "mąka" are the same flour, as in the nutrition view.
--
-- Optional lines are left out of the percentage. A line without a linked product can never match,
-- so it counts as missing (and is marked `unlinked`) instead of flattering the result.
-- A recipe with no required lines does not appear (there is nothing to match).
--
-- Row-Level Security: recipes, recipe_ingredients, pantry_items and staple_ingredients show only
-- the caller's rows; ingredients shows the shared catalog and the caller's own products.
WITH have AS (
    SELECT lower(i.canonical_name) AS name
    FROM pantry_items p
    JOIN ingredients i ON i.id = p.ingredient_id
    UNION
    SELECT lower(i.canonical_name)
    FROM staple_ingredients s
    JOIN ingredients i ON i.id = s.ingredient_id
    UNION
    SELECT name FROM default_staples
),
required_lines AS (
    SELECT
        r.id          AS recipe_id,
        r.title,
        ri.id         AS line_id,
        ri.position,
        ri.raw_text,
        (i.id IS NULL)             AS unlinked,
        (h.name IS NOT NULL)       AS have_it
    FROM recipes r
    JOIN recipe_ingredients ri ON ri.recipe_id = r.id AND NOT ri.is_optional
    LEFT JOIN ingredients i    ON i.id = ri.ingredient_id
    LEFT JOIN have h           ON h.name = lower(i.canonical_name)
    WHERE r.deleted_at IS NULL
),
scored AS (
    SELECT
        recipe_id,
        title,
        count(*)                                    AS lines_total,
        count(*) FILTER (WHERE have_it)             AS lines_have,
        count(*) FILTER (WHERE NOT have_it)         AS lines_missing,
        jsonb_agg(
            jsonb_build_object('line_id', line_id, 'raw_text', raw_text, 'unlinked', unlinked)
            ORDER BY position
        ) FILTER (WHERE NOT have_it)                AS missing
    FROM required_lines
    GROUP BY recipe_id, title
)
SELECT
    recipe_id,
    title,
    lines_total,
    lines_have,
    round(100.0 * lines_have / lines_total, 1)      AS percent,
    COALESCE(missing, '[]'::jsonb)                  AS missing
FROM scored
WHERE 100.0 * lines_have / lines_total >= :min_percent
ORDER BY percent DESC, lines_missing, title, recipe_id
LIMIT :limit
