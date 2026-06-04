-- Migration 0043: fix two muscle-mapping inversions flagged by the sports-science
-- panel review (M6).
--
-- (1) Deadlift was seeded primary 'back' in 0025, which the blanket back→lats
--     remap in 0040 turned into 'lats' — crediting a hip-hinge's stimulus to the
--     lats and only 0.5 to the posterior chain that actually does the work.
--     Re-credit as a posterior-chain movement (glutes primary; hams/erectors/
--     traps secondary; lats retained as a stabilizer secondary).
-- (2) Overhead/shoulder PRESSES collapsed to 'side_delts' via the Hevy
--     'shoulders'→side_delts normalization — but presses are front-delt dominant.
--     Flip presses to front_delts primary, keep side_delts as a secondary.
--     Lateral raises / upright rows do NOT match the press filter, so they keep
--     side_delts correctly.

-- ── 1. Deadlift variants mis-credited to lats (excludes RDL/stiff-leg, which
--       0025 already mapped to hamstrings) ──────────────────────────────────────
UPDATE exercise_muscle_map
SET primary_muscle = 'glutes',
    secondary_muscles = list_distinct(
        list_concat(secondary_muscles, ['hamstrings', 'lower_back', 'traps'])
    )
WHERE lower(exercise_name) LIKE '%deadlift%'
  AND primary_muscle = 'lats';

-- ── 2. Presses mis-credited to side_delts → front_delts primary ───────────────
UPDATE exercise_muscle_map
SET primary_muscle = 'front_delts',
    secondary_muscles = list_distinct(list_append(secondary_muscles, 'side_delts'))
WHERE primary_muscle = 'side_delts'
  AND (
        lower(exercise_name) LIKE '%press%'
     OR lower(exercise_name) LIKE '%overhead%'
     OR lower(exercise_name) LIKE '%military%'
  );
