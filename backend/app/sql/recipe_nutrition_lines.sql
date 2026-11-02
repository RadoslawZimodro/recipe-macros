-- Every ingredient line of a recipe with its weight, nutrition and (if any) what is missing.
SELECT
    line_id,
    position,
    raw_text,
    is_optional,
    quantity,
    unit_code,
    product_id,
    product_name,
    macro_source,
    grams,
    weight_source,
    is_estimate,
    kcal,
    protein,
    fat,
    carbs,
    problem
FROM recipe_line_nutrition
WHERE recipe_id = :recipe_id
ORDER BY position
