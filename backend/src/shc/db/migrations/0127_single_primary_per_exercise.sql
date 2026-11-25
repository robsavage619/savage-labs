-- Migration 0127: one primary muscle per exercise.
--
-- 0077 inserted lower_back rows for the hinge lifts with the column default
-- role = 'primary'. Smith Machine Stiff-Legged Deadlift already had hamstrings as
-- its primary, so it ended up with two. The exercise_muscle_map view collapses an
-- exercise to one primary with MAX(muscle), which is alphabetical: lower_back beat
-- hamstrings, and the volume engine stopped crediting hamstrings for Rob's
-- highest-volume hinge. Found 2026-11-24 when the weekly volume vs raw credit sum
-- reconcile check read hamstrings 3.0 (engine) against 5.0 (raw).
--
-- lower_back stays on the row for its region, length bias and SFR; it is the
-- secondary mover on a stiff-legged deadlift, with the stored secondary credit.

UPDATE exercise_muscle
SET role = 'secondary', credit = 0.5
WHERE exercise_name = 'Smith Machine Stiff-Legged Deadlift'
  AND muscle = 'lower_back'
  AND role = 'primary';

-- Same shape on Plank: 0025 mapped it to the retired 'core', 0077 added 'abs', and
-- the view picked 'core' (alphabetically last). The runtime backfill already remaps
-- core to abs on live; this does it for a database built from migrations alone.
DELETE FROM exercise_muscle
WHERE exercise_name = 'Plank' AND muscle = 'core' AND role = 'primary'
  AND EXISTS (
    SELECT 1 FROM exercise_muscle a
    WHERE a.exercise_name = 'Plank' AND a.muscle = 'abs' AND a.role = 'primary'
  );
