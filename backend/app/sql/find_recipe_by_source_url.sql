-- The user's active recipe imported from this (normalized) address, if any.
-- Row-Level Security limits the search to the current user's rows.
SELECT id
FROM recipes
WHERE source_url = :source_url
  AND deleted_at IS NULL
