-- Migration 0041: complete exercise_muscle_map coverage.
--
-- The live /api/training/muscle-volume endpoint reported these exercises trained
-- but unmapped (so their sets credited no muscle). Map them with canonical
-- vocabulary (see 0040). Then re-run the dynamic Hevy-template join from 0038 so
-- any exercise with a Hevy template that synced since is auto-mapped too.

-- ── 1. Explicit rows for known unmapped exercises (no Hevy template) ─────────
INSERT OR IGNORE INTO exercise_muscle_map
    (exercise_name, primary_muscle, secondary_muscles) VALUES
    ('Bicep Curl (Cable)',           'biceps',     []),
    ('Crunch (Machine)',             'abs',        []),
    ('Cable Core Pallof Press',      'abs',        []),
    ('Hammerstrength Shoulder Press', 'side_delts', ['front_delts', 'triceps']),
    ('Rear Delt Reverse Fly (Dumbbell)', 'rear_delts', ['traps']);

-- ── 2. Re-run the dynamic Hevy-template seed (0038), normalized to canonical ─
-- Hevy's own classification is authoritative + granular; only fills gaps.
INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles)
SELECT DISTINCT
    ws.exercise AS exercise_name,
    CASE LOWER(t.primary_muscle_group)
        WHEN 'upper_back'  THEN 'mid_back'
        WHEN 'quadriceps'  THEN 'quads'
        WHEN 'abdominals'  THEN 'abs'
        WHEN 'abductors'   THEN 'glutes'
        WHEN 'shoulders'   THEN 'side_delts'
        WHEN 'back'        THEN 'lats'
        ELSE LOWER(t.primary_muscle_group)
    END AS primary_muscle,
    [] AS secondary_muscles
FROM workout_sets ws
JOIN hevy_exercise_templates t ON t.id = ws.exercise_template_id
WHERE ws.exercise_template_id IS NOT NULL
  AND t.primary_muscle_group IS NOT NULL
  AND ws.exercise NOT IN (SELECT exercise_name FROM exercise_muscle_map);
