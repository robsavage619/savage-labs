-- Migration 0065: make muscle-level (MEV/MAV/MRV) volume crediting agree with
-- the anatomy the exercise_science layer already knows.
--
-- exercise_muscle_map is the single source of truth for weekly_muscle_volume, but
-- 14 curated movements named a muscle in exercise_science that the map did NOT
-- credit — so, e.g., a hammer curl built brachioradialis COVERAGE (region ledger)
-- yet contributed zero to the forearms VOLUME target, and rows never counted
-- toward mid_back. This backfills those missing secondaries so the landmark
-- engine stops under-counting real indirect work. Each is credited at the
-- existing rate (ARM_SECONDARY_CREDIT 0.3 for forearms, SECONDARY_CREDIT 0.5
-- otherwise) — anatomically standard synergist volume, verified on 8 weeks of
-- real data to move every muscle proportionally and stay within its landmarks
-- (no muscle is pushed to a spurious cut/deload).
--
-- Guards (NOT list_contains) make each append idempotent.

-- Rows / face pull → mid_back (rhomboids + mid traps do real work on every row).
UPDATE exercise_muscle_map
SET secondary_muscles = list_append(secondary_muscles, 'mid_back')
WHERE exercise_name IN ('Bent Over Row (Barbell)', 'Seated Cable Row', 'T-Bar Row', 'Face Pull')
  AND NOT list_contains(secondary_muscles, 'mid_back');

-- Squats / lunges / leg press → adductors (hip stabilization + extension).
UPDATE exercise_muscle_map
SET secondary_muscles = list_append(secondary_muscles, 'adductors')
WHERE exercise_name IN ('Squat (Barbell)', 'Lunge (Barbell)', 'Leg Press (Machine)',
                        'Bulgarian Split Squat (Dumbbell)')
  AND NOT list_contains(secondary_muscles, 'adductors');

-- Hinges → lower_back (spinal erectors braced isometrically under load).
UPDATE exercise_muscle_map
SET secondary_muscles = list_append(secondary_muscles, 'lower_back')
WHERE exercise_name IN ('Romanian Deadlift (Barbell)', 'Good Morning (Barbell)')
  AND NOT list_contains(secondary_muscles, 'lower_back');

-- Neutral-grip curls → forearms (brachioradialis is a prime mover here).
UPDATE exercise_muscle_map
SET secondary_muscles = list_append(secondary_muscles, 'forearms')
WHERE exercise_name IN ('Hammer Curl (Dumbbell)', 'Hammer Curls')
  AND NOT list_contains(secondary_muscles, 'forearms');

-- Dumbbell overhead press → side_delts (the free-weight press hits lateral head).
UPDATE exercise_muscle_map
SET secondary_muscles = list_append(secondary_muscles, 'side_delts')
WHERE exercise_name = 'Overhead Press (Dumbbell)'
  AND NOT list_contains(secondary_muscles, 'side_delts');

-- Fix a misclassification the "curl" substring caused: a wrist curl is a FOREARM
-- movement, not biceps. Its exercise_science row is already forearms; correct the
-- map primary so its volume credits forearms (and stops inflating biceps).
UPDATE exercise_muscle_map
SET primary_muscle = 'forearms', secondary_muscles = []
WHERE exercise_name IN ('Palms-Down Dumbbell Wrist Curl', 'Palms-Up Dumbbell Wrist Curl')
  AND primary_muscle != 'forearms';
