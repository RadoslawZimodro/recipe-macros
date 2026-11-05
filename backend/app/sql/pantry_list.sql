-- The products on one of the user's lists, with their names. :list is 'pantry' or 'staples'
-- (the two tables have the same shape); :ingredient_id optionally narrows it to one product.
-- Row-Level Security limits both tables to the caller's rows.
SELECT x.ingredient_id, i.canonical_name AS name, x.added_at
FROM (
    SELECT ingredient_id, added_at FROM pantry_items WHERE :list = 'pantry'
    UNION ALL
    SELECT ingredient_id, added_at FROM staple_ingredients WHERE :list = 'staples'
) x
JOIN ingredients i ON i.id = x.ingredient_id
WHERE CAST(:ingredient_id AS integer) IS NULL OR x.ingredient_id = :ingredient_id
ORDER BY lower(i.canonical_name), x.ingredient_id
