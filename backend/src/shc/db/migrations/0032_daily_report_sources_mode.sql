-- Add vault citations and pre/post-workout mode to the unified daily report.
-- DuckDB can't ADD COLUMN with NOT NULL/DEFAULT constraints, so these are plain
-- nullable columns; the API treats a NULL `sources` as an empty list.
ALTER TABLE ai_daily_report ADD COLUMN IF NOT EXISTS sources TEXT;  -- JSON array of vault filenames
ALTER TABLE ai_daily_report ADD COLUMN IF NOT EXISTS mode VARCHAR;  -- 'pre_workout' | 'post_workout'

INSERT INTO schema_version (version) VALUES (32) ON CONFLICT DO NOTHING;
