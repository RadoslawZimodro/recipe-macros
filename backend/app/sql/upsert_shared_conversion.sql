-- Grams per ONE unit of a shared product (an egg: 55 g). Idempotent.
INSERT INTO unit_conversions (ingredient_id, user_id, unit_code, grams_per_unit, source)
VALUES (:product_id, NULL, :unit, :grams, 'manual')
ON CONFLICT (ingredient_id, unit_code) WHERE ingredient_id IS NOT NULL AND user_id IS NULL
DO UPDATE SET grams_per_unit = EXCLUDED.grams_per_unit
