-- File name and type of one step's picture. Row-Level Security limits recipe_steps and recipes
-- to the current user; a soft-deleted recipe has no pictures to show.
SELECT s.image_path, s.image_content_type
FROM recipe_steps s
JOIN recipes r ON r.id = s.recipe_id
WHERE s.recipe_id = :recipe_id
  AND s.position = :position
  AND s.image_path IS NOT NULL
  AND r.deleted_at IS NULL
