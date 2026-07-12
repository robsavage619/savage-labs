-- Quarantine contaminated Hammer Curl (Dumbbell) sets (Apr 2026).
--
-- Rob logs hammer curls per-hand in Hevy; his real working load is 30–50 lb per
-- hand (Jun–Jul 2026). A cluster of 15 sets from Apr 7–29 at 120–130 lb is not a
-- real per-hand dumbbell load (no such dumbbell exists) — a mis-entry that, once
-- the erroneous ÷2 "combined-weight" halving was removed (commit "stop halving
-- dumbbell loads"), surfaced as a "170 lb each hand" ceiling (e1RM 152, ceiling
-- ~108). It defeats the median/MAD outlier guard because it is a *cluster*, not a
-- lone spike. Confirmed with Rob 2026-07-12: quarantine.
--
-- Mechanism: mark the sets is_warmup = TRUE. Non-destructive and reversible — the
-- rows stay in history but drop out of the e1RM/ceiling math (e1rm_by_exercise and
-- the weekly-e1RM backfill both exclude warmups), so the load ceiling reflects his
-- true recent per-hand capacity. Scoped precisely so no legitimate set is touched
-- (there are zero post-April Hammer Curl sets above 32 kg).

UPDATE workout_sets
SET is_warmup = TRUE
WHERE id IN (
    SELECT ws.id
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.exercise = 'Hammer Curl (Dumbbell)'
      AND w.source = 'hevy'
      AND w.started_at >= DATE '2026-04-01'
      AND w.started_at <  DATE '2026-05-01'
      AND ws.weight_kg > 32.0   -- ~70 lb; real per-hand hammer curls sit far below
);
