-- Entries of the food log with their nutrition, from the food_log_nutrition view.
-- Either one day (:day, in :tz; same boundaries and index use as food_log_days.sql)
-- or a single entry (:log_id); the unused filter is passed as NULL.
SELECT
    n.log_id,
    n.logged_at,
    n.recipe_id,
    n.ingredient_id,
    n.servings,
    n.grams,
    n.name,
    n.lines_total,
    n.lines_counted,
    n.is_estimate,
    n.complete,
    n.kcal,
    n.protein,
    n.fat,
    n.carbs
FROM food_log_nutrition n
WHERE (CAST(:log_id AS integer) IS NULL OR n.log_id = :log_id)
  AND (CAST(:day AS date) IS NULL OR (
        n.logged_at >= CAST(CAST(:day AS date) AS timestamp) AT TIME ZONE :tz
    AND n.logged_at <  CAST(CAST(:day AS date) + 1 AS timestamp) AT TIME ZONE :tz))
ORDER BY n.logged_at, n.log_id
