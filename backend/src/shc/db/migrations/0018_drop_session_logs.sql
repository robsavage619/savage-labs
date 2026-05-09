-- Reverse 0017. Rob logs every workout in Hevy; SHC never captures live sets.
-- Autoregulation now derives from workout_sets_dedup post-sync, not in-app input.

DROP INDEX IF EXISTS idx_session_set_logs_exercise;
DROP INDEX IF EXISTS idx_session_set_logs_date;
DROP TABLE IF EXISTS session_set_logs;

INSERT INTO schema_version (version) VALUES (18) ON CONFLICT DO NOTHING;
