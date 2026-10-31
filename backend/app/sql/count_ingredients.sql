-- Total number of products matching the same filter as search_ingredients.sql.
SELECT count(*)
FROM ingredients g
WHERE CAST(:q AS text) IS NULL
   OR g.canonical_name ILIKE :pattern
   OR g.canonical_name % CAST(:q AS text)
