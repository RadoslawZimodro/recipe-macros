-- One recipe with its steps and ingredient lines in a single round trip.
-- Two correlated sub-queries aggregate the children into JSON arrays, ordered by position.
-- Row-Level Security filters every table to the current user, so no user_id is needed here.
SELECT
    r.id,
    r.title,
    r.description,
    r.source_url,
    r.servings,
    r.image_url,
    CASE WHEN r.cover_path IS NOT NULL THEN '/recipes/' || r.id || '/cover' END AS cover_url,
    r.prep_time_min,
    r.cook_time_min,
    r.tags,
    r.source_nutrition,
    r.import_method,
    r.imported_at,
    r.created_at,
    r.updated_at,
    COALESCE((
        SELECT json_agg(
            json_build_object(
                'position', s.position,
                'instruction', s.instruction,
                'image_url', CASE WHEN s.image_path IS NOT NULL
                    THEN '/recipes/' || r.id || '/steps/' || s.position || '/image' END
            )
            ORDER BY s.position
        )
        FROM recipe_steps s
        WHERE s.recipe_id = r.id
    ), '[]'::json) AS steps,
    COALESCE((
        SELECT json_agg(
            json_build_object(
                'id', i.id,
                'position', i.position,
                'raw_text', i.raw_text,
                'quantity', i.quantity,
                'unit', i.unit_code,
                'is_optional', i.is_optional,
                'grams', i.grams_manual,
                'ingredient_id', i.ingredient_id,
                'ingredient_name', g.canonical_name
            )
            ORDER BY i.position
        )
        FROM recipe_ingredients i
        LEFT JOIN ingredients g ON g.id = i.ingredient_id
        WHERE i.recipe_id = r.id
    ), '[]'::json) AS ingredients
FROM recipes r
WHERE r.id = :recipe_id
  AND r.deleted_at IS NULL
