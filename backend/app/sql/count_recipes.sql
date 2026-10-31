-- Total number of recipes matching the same filters as list_recipes.sql (for pagination).
SELECT count(*)
FROM recipes r
WHERE r.deleted_at IS NULL
  AND (
        CAST(:q AS text) IS NULL
        OR r.title ILIKE :pattern
        OR r.title % CAST(:q AS text)
      )
  AND (CAST(:tag AS text) IS NULL OR r.tags @> ARRAY[CAST(:tag AS text)])
