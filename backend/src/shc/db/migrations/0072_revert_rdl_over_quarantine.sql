-- Revert the Romanian Deadlift (Dumbbell) rows that 0071 quarantined in error.
--
-- 0071 tested the RAW logged weight against the 105 lb per-hand ceiling. That is
-- wrong for the handful of lifts in load_mechanics._LOGGED_AS_COMBINED, which Rob
-- enters as a two-dumbbell TOTAL — 'Romanian Deadlift (Dumbbell)' is currently
-- the only member. Its logged 150 lb is 75 lb per hand, comfortably legal, so
-- the bound should never have fired.
--
-- Effect of the bug: 6 legitimate working sets (2026-06-11 and 2026-06-14) were
-- marked is_warmup, dropping the RDL working weight from a true 75 lb/hand to
-- 45 and the ceiling from ~61 lb to 36.9 — under-prescribing the lift.
--
-- The rule 0071 should have applied, and which the sync-time guard now enforces:
-- compare per_hand_kg(name, logged_kg) against the ceiling, never the raw logged
-- value. per_hand_kg is the documented single choke point every e1RM / ceiling /
-- prescription path routes through.
--
-- Safe to scope by weight: every legitimate RDL set in this window is <= 90 lb
-- logged and was never touched, so the only is_warmup rows above the threshold
-- are the six 0071 created. No genuine warmup is un-flagged.

UPDATE workout_sets
SET is_warmup = FALSE
WHERE id IN (
    SELECT ws.id
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.exercise = 'Romanian Deadlift (Dumbbell)'
      AND ws.is_warmup = TRUE
      AND ws.weight_kg * 2.20462 > 105.5
      AND w.started_at >= DATE '2026-04-19'
);
