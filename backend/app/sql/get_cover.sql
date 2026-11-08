-- File name and type of a recipe's photo. Row-Level Security limits recipes to the current
-- user; a soft-deleted recipe has nothing to show.
SELECT cover_path, cover_content_type
FROM recipes
WHERE id = :recipe_id
  AND cover_path IS NOT NULL
  AND deleted_at IS NULL
