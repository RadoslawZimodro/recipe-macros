-- Macros per 100 g of the given USDA foods (one row per food, from the usda_food_macros view).
-- Foods the staging tables do not contain are simply absent from the result.
SELECT fdc_id, description, kcal, protein, fat, carbs
FROM usda_food_macros
WHERE fdc_id = ANY(:ids)
