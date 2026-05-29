-- Capture Hevy fields that were silently dropped during ingest.
-- exercise_template_id is the most impactful: it lets us JOIN to hevy_exercise_templates
-- to use Hevy's own authoritative muscle group classification instead of keyword matching.

ALTER TABLE workout_sets ADD COLUMN IF NOT EXISTS exercise_template_id VARCHAR;
ALTER TABLE workout_sets ADD COLUMN IF NOT EXISTS duration_seconds     INTEGER;
ALTER TABLE workout_sets ADD COLUMN IF NOT EXISTS superset_id          VARCHAR;
ALTER TABLE workout_sets ADD COLUMN IF NOT EXISTS exercise_index       INTEGER;

ALTER TABLE workouts ADD COLUMN IF NOT EXISTS routine_id VARCHAR;

-- Index for muscle group JOINs via template
CREATE INDEX IF NOT EXISTS idx_workout_sets_template_id
    ON workout_sets (exercise_template_id);
