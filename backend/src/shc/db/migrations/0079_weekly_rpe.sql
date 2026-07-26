-- 0079: carry weekly average RPE in the e1RM rollup so effort becomes a
-- first-class progression signal instead of a session-level afterthought.
--
-- score_exercise -- the signal that drives _muscle_performance and therefore
-- every volume decision in _decide -- was built entirely from e1RM slope with a
-- tonnage tiebreak. RPE reached the engine in exactly two places, both global
-- (cross-muscle) and both weak: _rpe_drift_factor (dampens volume adds) and
-- _rpe_headroom (flips a stalled muscle's advice from "add a set" to "add
-- load"). Neither could tell these four situations apart, and they need
-- opposite responses:
--
--   flat e1RM + FALLING RPE  -> real progression (same load, less effort)
--   flat e1RM + RISING  RPE  -> hidden regression (same load, more cost)
--   rising e1RM + flat  RPE  -> clean progression
--   rising e1RM + rising RPE -> borrowing against recovery
--
-- All four scored identically (perf 3 when flat, 4/5 when rising). Effort is
-- the earliest honest read on whether adaptation is actually happening, so it
-- belongs in the score, not beside it.
--
-- NULL is meaningful here and must stay meaningful: Rob only began logging RPE
-- around 2026-05, so ~87% of historical sets carry none. Every consumer treats
-- NULL as "no effort claim" and falls back to the pre-0079 e1RM-only score.

ALTER TABLE exercise_weekly_e1rm ADD COLUMN IF NOT EXISTS weekly_avg_rpe DOUBLE;
ALTER TABLE exercise_weekly_e1rm ADD COLUMN IF NOT EXISTS rpe_set_count INTEGER;

-- Backfill from logged history. Averaged over WORKING sets only (warmups carry
-- a deliberately low RPE that would drag the weekly mean down and manufacture a
-- false "getting easier" signal).
UPDATE exercise_weekly_e1rm AS t
SET weekly_avg_rpe = src.avg_rpe,
    rpe_set_count  = src.n_rpe
FROM (
    SELECT exercise,
           date_trunc('week', started_at)::DATE AS week_start,
           AVG(rpe)   AS avg_rpe,
           COUNT(rpe) AS n_rpe
    FROM workout_sets_dedup
    WHERE weight_kg > 0 AND reps > 0
      AND source = 'hevy' AND is_warmup = FALSE
      AND rpe IS NOT NULL
    GROUP BY exercise, date_trunc('week', started_at)::DATE
) AS src
WHERE t.exercise = src.exercise AND t.week_start = src.week_start;
