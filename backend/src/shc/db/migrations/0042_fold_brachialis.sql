-- Migration 0042: fold 'brachialis' into 'biceps'.
--
-- 'brachialis' appears only as a secondary muscle (e.g. Hammer Curl) and is not a
-- body-diagram region, so it surfaced as an untargeted muscle in the volume
-- report. It is an elbow flexor trained with the biceps — credit it there.

UPDATE exercise_muscle_map SET primary_muscle = 'biceps' WHERE primary_muscle = 'brachialis';

-- Drop 'brachialis' from secondaries (don't remap → biceps, which would
-- double-credit the curls that already have biceps as primary).
UPDATE exercise_muscle_map
SET secondary_muscles = list_filter(secondary_muscles, x -> x != 'brachialis')
WHERE list_contains(secondary_muscles, 'brachialis');
