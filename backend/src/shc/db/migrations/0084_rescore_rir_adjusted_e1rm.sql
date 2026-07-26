-- 0084: invalidate perf scores derived from the pre-RIR e1RM basis.
--
-- e1RM is now Epley over RIR-ADJUSTED reps (load_mechanics.effective_reps_sql):
-- Epley assumes the set went to failure, and Rob's best sets sit at RPE 7-8,
-- so raw reps understated it. Because the day's load ceiling is a PERCENTAGE
-- of e1RM, that understatement compounded into the prescription — a MODERATE
-- day's 90% cap landed near 64% of what he had lifted three days earlier at the
-- same target RPE (Leg Extension: 200x10 @RPE 8 logged 2026-07-23, then 175x10
-- prescribed at "RPE 8" on 2026-07-26).
--
-- `backfill_weekly_e1rm` upserts `e1rm_kg` on every run, so the stored e1RM
-- self-heals on the next `compute_all_scores`. `backfill_perf_scores` does NOT:
-- it only fills NULL cells, deliberately, so previously-computed scores are
-- preserved. That protection becomes a trap here — those scores were fitted
-- against a basis that no longer exists, and would sit next to refreshed e1RM
-- values forever, silently mixing two bases in one series.
--
-- So: null the scores for exactly the weeks whose e1RM actually moves — the
-- ones carrying RPE. Weeks with no RPE (~87% of history) are unchanged by the
-- new expression and keep their scores, which also keeps the re-score cheap and
-- its blast radius auditable.

UPDATE exercise_weekly_e1rm
SET perf_score = NULL,
    trend = NULL
WHERE COALESCE(rpe_set_count, 0) > 0;
