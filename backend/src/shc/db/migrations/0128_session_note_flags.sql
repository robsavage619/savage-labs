-- Tags derived from the free-text notes Rob leaves in Hevy (workout description
-- and per-exercise notes). exercise = '' means the whole session. Rebuilt from
-- workouts.notes / workout_sets.exercise_notes by shc.training.session_notes, never
-- written by hand. excludes_e1rm rows drop the matching sets from every e1RM,
-- ceiling and progression-trend query; volume and tonnage still count them.
CREATE TABLE IF NOT EXISTS session_note_flags (
    workout_id   VARCHAR NOT NULL,
    exercise     VARCHAR NOT NULL,
    tag          VARCHAR NOT NULL,
    note         VARCHAR NOT NULL,
    excludes_e1rm BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_note_flags_workout ON session_note_flags (workout_id);
