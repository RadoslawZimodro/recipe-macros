-- Totals per calendar day for :date_from .. :date_to (inclusive), compared with the user's goals.
--
-- "Day" means the calendar day in :tz (Europe/Warsaw), not in UTC: timestamps are stored as
-- timestamptz (an instant), and an entry at 00:30 Polish time belongs to the NEW day even though
-- it is still the previous evening in UTC.
--
-- The WHERE clause compares logged_at with the day's boundaries instead of casting logged_at to
-- a date. That keeps the condition usable by the index (user_id, logged_at): Postgres reads only
-- the needed range instead of computing a date for every row of the user.
--
-- Days without entries are still returned (zeros), because the series of days is generated
-- first and the totals are joined to it: a chart needs the empty days too.
-- Row-Level Security applies through the view (security_invoker): only the caller's rows.
WITH bounds AS (
    SELECT CAST(:date_from AS date) AS d_from,
           CAST(:date_to AS date)   AS d_to
),
eaten AS (
    SELECT
        CAST(n.logged_at AT TIME ZONE :tz AS date)  AS day,
        count(*)                                    AS entries,
        COALESCE(sum(n.kcal), 0)                    AS kcal,
        COALESCE(sum(n.protein), 0)                 AS protein,
        COALESCE(sum(n.fat), 0)                     AS fat,
        COALESCE(sum(n.carbs), 0)                   AS carbs,
        bool_or(n.is_estimate)                      AS is_estimate,
        bool_and(n.complete)                        AS complete
    FROM food_log_nutrition n
    CROSS JOIN bounds b
    WHERE n.logged_at >= CAST(b.d_from AS timestamp) AT TIME ZONE :tz
      AND n.logged_at <  CAST(b.d_to + 1 AS timestamp) AT TIME ZONE :tz
    GROUP BY 1
),
goals AS (
    SELECT daily_kcal_goal, daily_protein_goal
    FROM users
    WHERE id = app_current_user_id()
)
SELECT
    b.d_from + s.n                          AS day,
    COALESCE(e.entries, 0)                  AS entries,
    COALESCE(e.kcal, 0)                     AS kcal,
    COALESCE(e.protein, 0)                  AS protein,
    COALESCE(e.fat, 0)                      AS fat,
    COALESCE(e.carbs, 0)                    AS carbs,
    COALESCE(e.is_estimate, false)          AS is_estimate,
    COALESCE(e.complete, true)              AS complete,
    g.daily_kcal_goal                       AS kcal_goal,
    g.daily_kcal_goal - COALESCE(e.kcal, 0) AS kcal_remaining,
    round(100 * COALESCE(e.kcal, 0) / g.daily_kcal_goal, 1)       AS kcal_percent,
    g.daily_protein_goal                    AS protein_goal,
    g.daily_protein_goal - COALESCE(e.protein, 0)                 AS protein_remaining,
    round(100 * COALESCE(e.protein, 0) / g.daily_protein_goal, 1) AS protein_percent
FROM bounds b
CROSS JOIN LATERAL generate_series(0, b.d_to - b.d_from) AS s(n)
LEFT JOIN eaten e ON e.day = b.d_from + s.n
CROSS JOIN goals g
ORDER BY day
