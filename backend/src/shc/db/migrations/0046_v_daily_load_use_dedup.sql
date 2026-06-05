-- Migration 0046: redefine v_daily_load to join workout_sets_dedup instead of
-- raw workout_sets, so Fitbod+Hevy overlap days don't double-count the
-- resistance ACWR/load signal.

CREATE OR REPLACE VIEW v_daily_load AS
SELECT
    d.date,
    COALESCE(s.whoop_strain, 0) AS whoop_strain,
    COALESCE(h.hevy_volume_kg, 0) / 1000.0 AS hevy_tonnes,
    -- Composite load: WHOOP strain (0–21 scale) + scaled Hevy tonnes (~0–5).
    COALESCE(s.whoop_strain, 0) + COALESCE(h.hevy_volume_kg, 0) / 5000.0 AS composite_load
FROM (
    SELECT date FROM v_session_load
    UNION
    SELECT started_at::DATE AS date FROM workouts
) d
LEFT JOIN v_session_load s ON s.date = d.date
LEFT JOIN (
    SELECT w.started_at::DATE AS date,
           SUM(ws.weight_kg * ws.reps) AS hevy_volume_kg
    FROM workout_sets_dedup ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.is_warmup = FALSE
    GROUP BY w.started_at::DATE
) h ON h.date = d.date;
