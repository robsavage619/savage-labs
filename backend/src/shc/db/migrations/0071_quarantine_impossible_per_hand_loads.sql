-- Quarantine per-hand loads above Rob's confirmed 105 lb per-hand ceiling.
--
-- Rob confirmed 2026-07-18: "105 has been my max per hand." That is a hard
-- physical bound, so any set on a per-hand-classified lift logging more than
-- 105 lb in ONE hand is a mis-entry, not a training record.
--
-- Scope is deliberately narrow. A survey found 10,262 dumbbell sets above 105 lb
-- per hand going back to 2017 — but that is a DIFFERENT problem and is NOT
-- touched here. Those maxima are clean doubles (220/200/198/176/160/140 =
-- 2x110/100/99/88/80/70), i.e. the pre-2026 history looks like it was recorded
-- as combined totals while current logging is per-hand. Acting on that premise
-- is exactly what corrupted every dumbbell ceiling before (see the per-hand
-- identity rule in CLAUDE.md: per_hand_kg is the IDENTITY, never halve). It also
-- no longer causes harm: both e1rm_by_exercise and the WORKING WEIGHTS display
-- read a 90d window, so pre-2026 rows have already rolled out of every live
-- ceiling. Left alone pending an explicit decision from Rob.
--
-- What IS quarantined: the 25 sets that fall inside the live 90d window, where
-- current-era per-hand logging and an impossible value coexist. These inflate
-- ceilings the planner can prescribe from right now:
--   Incline Bench Press (Dumbbell)  5 sets  max 160 lb  last 2026-05-19
--   Romanian Deadlift (Dumbbell)    6 sets  max 150 lb  last 2026-06-14
--   Cable Fly Crossovers / Cable Crossover Fly  8 sets  max 135 lb  2026-04-22
--   Hammer Curls                    4 sets  max 130 lb  last 2026-04-21
--   Bench Press (Dumbbell)          2 sets  max 110 lb  last 2026-05-15
--
-- Mechanism matches 0069: mark is_warmup = TRUE. Non-destructive and reversible
-- — rows stay in history but drop out of the e1RM/ceiling math (e1rm_by_exercise
-- and the weekly-e1RM backfill both exclude warmups).
--
-- Bilateral lifts (barbell, machine, single-stack cable) are excluded: their
-- logged number is a whole-implement load, so 105 does not bound them. The name
-- list below is the per-hand set only, and includes both the current and legacy
-- Hevy spellings of the same movement.

UPDATE workout_sets
SET is_warmup = TRUE
WHERE id IN (
    SELECT ws.id
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.weight_kg * 2.20462 > 105.5
      AND ws.is_warmup = FALSE
      AND w.started_at >= DATE '2026-04-19'
      AND ws.exercise IN (
          'Incline Bench Press (Dumbbell)',
          'Dumbbell Incline Bench Press',
          'Romanian Deadlift (Dumbbell)',
          'Cable Fly Crossovers',
          'Cable Crossover Fly',
          'Hammer Curls',
          'Hammer Curl (Dumbbell)',
          'Bench Press (Dumbbell)',
          'Dumbbell Bench Press'
      )
);
