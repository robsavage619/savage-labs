-- 0085: the resistance load arm was blind to effort.
--
-- `v_daily_load`'s resistance component was raw volume-load: SUM(weight x reps).
-- Tonnage is a fine hypertrophy VOLUME metric and a poor FATIGUE metric, and
-- this column is used as fatigue — it feeds `resistance_acwr`, which gates
-- today's intensity. The consequence is inverted:
--
--     3 x 5  @ RPE 9  =  15 reps of load  -> scores LOWER
--     3 x 15 @ RPE 6  =  45 reps of load  -> scores HIGHER
--
-- A heavy near-failure session registered as LESS load than an easy high-rep
-- one. So a shift toward heavier, lower-rep work reads to the engine as
-- detraining, and it responds by prescribing more volume — precisely backwards.
--
-- It compounds on propranolol days: `v_session_load` already excludes
-- powerlifting/weightlifting strain (correctly — lifting load belongs to this
-- arm, not the HR arm), and beta-blockade suppresses HR on the conditioning
-- arm, so both arms of composite_load could understate effort at once.
--
-- FIX. Weight each set's volume-load by its RPE, the multiplicative form Foster's
-- session-RPE uses (load = RPE x work), applied per set rather than per session
-- because Hevy grades at set level:
--
--     effort_load = SUM(weight_kg * reps * COALESCE(rpe, 7.0) / 7.0)
--
-- Reference 7.0 is the normaliser, not a threshold: it keeps the new series on
-- roughly the same scale as the old one (Rob's mean logged RPE is 7.21, so the
-- mean multiplier lands near 1.03) so the Gabbett thresholds — which are defined
-- against a ratio, and are scale-invariant WITHIN an arm — keep their meaning.
--
-- A set with NO logged RPE gets exactly 1.0 and is therefore unchanged. ~98% of
-- lifetime sets predate RPE logging; the historical series must not move under
-- an assumption, only under evidence. (Coverage is 100% over the last 30 days,
-- so the signal is live where it matters.)
--
-- `hevy_tonnes` is DELIBERATELY left as raw tonnage rather than redefined in
-- place: it is a truthful name for a real quantity, other readers may want it,
-- and keeping both columns lets the effort weighting be audited against the raw
-- series instead of silently replacing it.
--
-- SAFETY — why this needs no band re-fit. `self_learning.fit_acwr_bands` fits
-- ONLY the conditioning arm (`whoop_strain`; see self_learning.py:471/527/605),
-- and ENGINE_INVARIANTS #6 records that resistance ACWR is not fitted at all.
-- This migration touches only the resistance and composite columns, so the
-- fitter and the live gate cannot drift apart (invariant #1) as a result.

CREATE OR REPLACE VIEW v_daily_load AS
WITH comp AS (
    SELECT DISTINCT event_date AS date, 1.25 AS mult
    FROM dupr_matches
)
SELECT
    d.date,
    COALESCE(s.whoop_strain, 0) * COALESCE(c.mult, 1.0) AS whoop_strain,
    -- Raw volume-load, unchanged: kept truthful and auditable.
    COALESCE(h.hevy_volume_kg, 0) / 1000.0 AS hevy_tonnes,
    -- Effort-weighted resistance load — the fatigue basis the ACWR arm uses.
    COALESCE(h.hevy_effort_kg, 0) / 1000.0 AS hevy_effort_load,
    -- Composite: scaled WHOOP strain (0–21 base) + scaled effort-weighted load.
    COALESCE(s.whoop_strain, 0) * COALESCE(c.mult, 1.0)
        + COALESCE(h.hevy_effort_kg, 0) / 5000.0 AS composite_load
FROM (
    SELECT date FROM v_session_load
    UNION
    SELECT started_at::DATE AS date FROM workouts
) d
LEFT JOIN v_session_load s ON s.date = d.date
LEFT JOIN (
    SELECT w.started_at::DATE AS date,
           SUM(ws.weight_kg * ws.reps) AS hevy_volume_kg,
           -- COALESCE on rpe, NOT on the ratio: a missing grade must resolve to
           -- a 1.0 multiplier (no claim), never to 0 (set erased) and never to
           -- a borrowed neighbouring RPE.
           SUM(ws.weight_kg * ws.reps * (COALESCE(ws.rpe, 7.0) / 7.0)) AS hevy_effort_kg
    FROM workout_sets_dedup ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.is_warmup = FALSE
    GROUP BY w.started_at::DATE
) h ON h.date = d.date
LEFT JOIN comp c ON c.date = d.date;
