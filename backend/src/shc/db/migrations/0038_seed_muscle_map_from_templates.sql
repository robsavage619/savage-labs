-- Seed exercise_muscle_map from hevy_exercise_templates where we now have
-- exercise_template_id on workout_sets. Hevy's own classification is authoritative
-- and more granular than our keyword matcher.
--
-- Only inserts exercises that appear in actual workout history and have a template.
-- Hevy primary_muscle_group values map to our muscle keys (lats, biceps, triceps,
-- chest, shoulders, glutes, hamstrings, quads, traps, etc.).

INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles)
SELECT DISTINCT
    ws.exercise                        AS exercise_name,
    LOWER(t.primary_muscle_group)      AS primary_muscle,
    []                                 AS secondary_muscles
FROM workout_sets ws
JOIN hevy_exercise_templates t ON t.id = ws.exercise_template_id
WHERE ws.exercise_template_id IS NOT NULL
  AND t.primary_muscle_group IS NOT NULL
  AND ws.exercise NOT IN (SELECT exercise_name FROM exercise_muscle_map);
