-- Seated Dumbbell Curl joined load_mechanics._LOGGED_AS_COMBINED: every set
-- before 2026-09-24 was entered as a two-dumbbell TOTAL, and now halves to
-- per-hand through per_hand_sql(). The persisted progression rows were scored on
-- the raw totals, and backfill_weekly_e1rm refreshes e1rm_kg on conflict but
-- preserves perf_score/trend, so the stale grading would survive a re-run. Same
-- remedy as 0073, scoped to the one lift: both tables are fully derived from
-- workout_sets_dedup, and the next compute_all_scores() pass rebuilds them.

DELETE FROM exercise_weekly_e1rm WHERE exercise = 'Seated Dumbbell Curl';
DELETE FROM muscle_signal_cache;
