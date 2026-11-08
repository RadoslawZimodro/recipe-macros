-- Page of the user's active recipes, optionally filtered by title text and/or tag.
--   :q        title search. ILIKE '%q%' (:pattern, LIKE wildcards escaped) finds substrings,
--             and the pg_trgm operator % finds near matches / typos; both use ix_recipes_title_trgm.
--   :tag      exact tag, uses the GIN index ix_recipes_tags through the @> operator.
-- With a search term the best match comes first, otherwise the newest recipe does.
SELECT
    r.id,
    r.title,
    r.description,
    r.image_url,
    CASE WHEN r.cover_path IS NOT NULL THEN '/recipes/' || r.id || '/cover' END AS cover_url,
    r.servings,
    r.tags,
    r.prep_time_min,
    r.cook_time_min,
    r.source_url,
    r.import_method,
    r.created_at,
    r.updated_at
FROM recipes r
WHERE r.deleted_at IS NULL
  AND (
        CAST(:q AS text) IS NULL
        OR r.title ILIKE :pattern
        OR r.title % CAST(:q AS text)
      )
  AND (CAST(:tag AS text) IS NULL OR r.tags @> ARRAY[CAST(:tag AS text)])
ORDER BY
    CASE WHEN CAST(:q AS text) IS NULL THEN NULL ELSE similarity(r.title, CAST(:q AS text)) END
        DESC NULLS LAST,
    r.created_at DESC,
    r.id DESC
LIMIT :limit OFFSET :offset
