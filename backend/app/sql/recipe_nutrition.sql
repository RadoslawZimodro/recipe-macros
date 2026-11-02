-- Totals of one recipe, built on the recipe_line_nutrition view (one row per ingredient line).
--   lines_total    lines that count (optional lines only when :include_optional is true)
--   lines_counted  of those, the lines for which grams and nutrition could be worked out
--   kcal_measured  calories that come from data NOT estimated by the AI (measured or typed in)
-- Lines that could not be computed contribute nothing (NULLs are skipped by sum), so the total is
-- "what we know"; the caller reports the coverage next to it.
-- Row-Level Security applies through the view (security_invoker).
SELECT
    r.id AS recipe_id,
    r.servings,
    agg.lines_total,
    agg.lines_counted,
    agg.kcal,
    agg.protein,
    agg.fat,
    agg.carbs,
    agg.kcal_measured
FROM recipes r
CROSS JOIN LATERAL (
    SELECT
        count(*)                                                    AS lines_total,
        count(*) FILTER (WHERE l.kcal IS NOT NULL)                  AS lines_counted,
        COALESCE(sum(l.kcal), 0)                                    AS kcal,
        COALESCE(sum(l.protein), 0)                                 AS protein,
        COALESCE(sum(l.fat), 0)                                     AS fat,
        COALESCE(sum(l.carbs), 0)                                   AS carbs,
        COALESCE(sum(l.kcal) FILTER (WHERE NOT l.is_estimate), 0)   AS kcal_measured
    FROM recipe_line_nutrition l
    WHERE l.recipe_id = r.id
      AND (CAST(:include_optional AS boolean) OR NOT l.is_optional)
) agg
WHERE r.id = :recipe_id
  AND r.deleted_at IS NULL
