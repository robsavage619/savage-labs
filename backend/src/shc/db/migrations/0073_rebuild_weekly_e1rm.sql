-- Force a full rebuild of the progression e1RM/perf-score series and the
-- signal-quality cache derived from it.
--
-- backfill_weekly_e1rm/compute_all_scores now filter the progression basis to
-- source='hevy' AND is_warmup=FALSE and normalize weight through
-- per_hand_sql() (the same filters e1rm_by_exercise, the load-ceiling path,
-- already applied) — previously the progression e1RM pipeline had none of
-- these, so Fitbod history, quarantined impossible-per-hand sets, and
-- combined-total dumbbell logs all fed the trend/perf-score directly. A
-- plain re-run of the backfill does NOT fix already-scored rows:
-- backfill_weekly_e1rm preserves existing perf_score/trend by design, and
-- backfill_perf_scores only fills NULL cells. Both tables are fully derived
-- from workout_sets_dedup, so wiping them and letting the next
-- compute_all_scores() pass (nightly job, or POST /api/training/scores/recompute)
-- rebuild from the corrected basis is safe and lossless.

DELETE FROM exercise_weekly_e1rm;
DELETE FROM muscle_signal_cache;
