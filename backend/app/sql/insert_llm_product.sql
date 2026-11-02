-- A product the AI named that is not in the catalog yet: a PRIVATE product of the current user,
-- flagged source = 'llm_estimate' (its nutrition values are the AI's estimate).
-- If the user already has a product with this name (a parallel import got there first), nothing
-- is inserted and no row is returned.
INSERT INTO ingredients (
    user_id, canonical_name, kcal_per_100g, protein_per_100g, fat_per_100g, carbs_per_100g, source
)
VALUES (:user_id, :name, :kcal, :protein, :fat, :carbs, 'llm_estimate')
ON CONFLICT (user_id, lower(canonical_name)) WHERE user_id IS NOT NULL
DO NOTHING
RETURNING id
