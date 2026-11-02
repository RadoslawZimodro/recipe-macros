-- Store the AI's estimates of what a unit of a product weighs, as the CURRENT USER's own
-- conversions: (product id, unit, grams per ONE unit). For unit 'ml' the number is the density
-- in grams per millilitre.
--
-- An estimate is only a fallback, so it is stored only where nothing is known yet:
--   * not if a conversion for this product and unit is already visible to the user (a shared,
--     curated one, or their own earlier value): Row-Level Security limits the NOT EXISTS to
--     what the user can see, and an own row would shadow a shared one;
--   * not for 'ml' if the product row itself carries a density.
-- ON CONFLICT DO NOTHING covers the case of two imports running at once.
INSERT INTO unit_conversions (ingredient_id, user_id, unit_code, grams_per_unit, source)
SELECT v.ingredient_id, :user_id, v.unit_code, v.grams, 'llm_estimate'
FROM unnest(
         CAST(:ids AS integer[]),
         CAST(:units AS text[]),
         CAST(:grams AS numeric[])
     ) AS v(ingredient_id, unit_code, grams)
WHERE NOT EXISTS (
          SELECT 1
          FROM unit_conversions uc
          WHERE uc.ingredient_id = v.ingredient_id AND uc.unit_code = v.unit_code
      )
  AND (
          v.unit_code <> 'ml'
          OR NOT EXISTS (
              SELECT 1
              FROM ingredients g
              WHERE g.id = v.ingredient_id AND g.density_g_per_ml IS NOT NULL
          )
      )
ON CONFLICT DO NOTHING
