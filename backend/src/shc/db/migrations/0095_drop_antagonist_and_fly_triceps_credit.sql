-- 0095: remove two synergist claims the mechanics do not support.
--
-- Both were produced by `classify_exercise` and persisted by
-- `backfill_exercise_map`; the classifier itself is fixed in the same change, so
-- newly-logged names cannot reintroduce them. That fix does NOT retro-correct
-- these rows: the backfill only visits exercises with NO mapping at all, so an
-- exercise keeping its primary row is skipped forever. Hence this migration.
--
-- 1. ABDUCTION -> ADDUCTORS. The adductors are the antagonist of hip abduction:
--    they lengthen under the movement rather than working against resistance.
--    58 Hip Abduction (Machine) + 32 Machine Hip Abductor sets were crediting
--    them at 0.5, i.e. ~45 phantom adductor sets. This matters beyond the weekly
--    number because `fit_volume_landmarks` refits MEV/MAV/MRV from this same
--    credit path across 104 weeks, so the phantom volume was also setting the
--    target it was measured against.
--
--    Deliberately NOT touched: the mirror row `Hip Adduction (Machine) ->
--    glutes`. It is a weaker claim but a defensible one — the adductor magnus is
--    a genuine hip extensor sharing function with the glutes — and unlike the
--    abduction row it is not an antagonist relationship. Flagged for Rob rather
--    than decided here.
--
-- 2. FLY/CROSSOVER -> TRICEPS. The elbow angle is held fixed through a fly, so
--    the triceps never shorten against load. 1,301 logged fly/crossover sets
--    (Cable Fly Crossovers 564, Cable Crossover Fly 655, Low Cable Fly
--    Crossovers 82) were feeding the triceps ledger at 0.5 — a muscle that
--    already draws 57% of its volume from indirect credit and currently reads
--    HOLD at 3.9/4 sets. Migration 0064 had already recorded flyes as
--    front_delts-only; its ON CONFLICT DO NOTHING lost to the classifier row.
--
-- Both statements are idempotent.

DELETE FROM exercise_muscle
 WHERE muscle = 'adductors'
   AND role = 'secondary'
   AND (exercise_name ILIKE '%abduction%' OR exercise_name ILIKE '%abductor%'
        OR exercise_name ILIKE '%fire hydrant%');

DELETE FROM exercise_muscle
 WHERE muscle = 'triceps'
   AND role = 'secondary'
   AND (exercise_name ILIKE '%fly%' OR exercise_name ILIKE '%crossover%')
   AND exercise_name NOT ILIKE '%press%';
