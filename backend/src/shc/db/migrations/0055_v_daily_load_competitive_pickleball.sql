-- Migration 0055: up-weight competitive DUPR-match days in v_daily_load (#28).
--
-- Pickleball reaches the conditioning load/ACWR signal as undifferentiated WHOOP
-- strain. But a rated DUPR *match* is played at higher intensity than casual
-- rallying, so a match day carries more conditioning load per minute. This
-- redefines v_daily_load to scale the strain portion of a day's load by a
-- bounded competitive multiplier when that date has a logged DUPR match.
--
-- The multiplier (1.25) MUST stay in sync with
-- metrics.pickleball_match_load()['competitive_load_mult'] — that helper is the
-- readable hook; this view is where the blend actually lands. Only the strain
-- term is scaled; Hevy tonnes (resistance) are untouched. A day's strain is
-- dominated by its session, so scaling the whole day's strain is a deliberate,
-- conservative N=1 approximation rather than decomposing strain by session type.
--
-- self_learning.fit_acwr_bands fits conditioning bands on this same strain
-- column, so the nightly re-fit will absorb the change; no separate action.

CREATE OR REPLACE VIEW v_daily_load AS
WITH comp AS (
    SELECT DISTINCT event_date AS date, 1.25 AS mult
    FROM dupr_matches
)
SELECT
    d.date,
    COALESCE(s.whoop_strain, 0) * COALESCE(c.mult, 1.0) AS whoop_strain,
    COALESCE(h.hevy_volume_kg, 0) / 1000.0 AS hevy_tonnes,
    -- Composite load: scaled WHOOP strain (0–21 base) + scaled Hevy tonnes.
    COALESCE(s.whoop_strain, 0) * COALESCE(c.mult, 1.0)
        + COALESCE(h.hevy_volume_kg, 0) / 5000.0 AS composite_load
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
) h ON h.date = d.date
LEFT JOIN comp c ON c.date = d.date;
