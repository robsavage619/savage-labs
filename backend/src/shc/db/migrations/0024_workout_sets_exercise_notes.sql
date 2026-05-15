-- Add exercise-level notes from Hevy to workout_sets.
-- Hevy supports a notes field per exercise (not per set); we store it
-- on every set row so queries can filter WHERE exercise_notes IS NOT NULL.
ALTER TABLE workout_sets ADD COLUMN IF NOT EXISTS exercise_notes VARCHAR;
