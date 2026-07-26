-- 0086: two names for one movement, disagreeing about how it loads the muscle.
--
-- Found by `training/reconcile.py` on its first run, not by the suite.
--
--   Leg Extension          shortened   0 logged sets
--   Leg Extension (Machine) mid       557 logged sets
--   Seated Leg Curl        lengthened   0 logged sets
--   Seated Leg Curl (Machine) mid     278 logged sets
--
-- `length_bias` is a ranking key in `_select_grounded`, so a movement carrying
-- two answers makes selection depend on which name the menu happens to surface —
-- the same defect as Preacher Curl, which held both `shortened` and `lengthened`
-- across three rows. These are not different implements: a seated leg curl and a
-- leg extension ARE machines, so the bare name is an alias for the parenthesised
-- one, not a distinct movement. (Barbell-vs-dumbbell splits on Overhead Press
-- and Incline Bench Press were reviewed and deliberately LEFT: a dumbbell
-- genuinely travels past where a bar stops at the chest, so those two really do
-- load different muscle lengths.)
--
-- The parenthesised rows win because they carry both the logged history and the
-- vault-grounded citation. `Seated Leg Curl` additionally cited a specificity
-- note that says nothing about where a leg curl peaks, so its citation is
-- realigned to the same note as the row it now agrees with.
--
-- Rows are aligned rather than deleted: Fitbod history logs the bare names, so
-- deleting them would make that history uncurated and unselectable.

-- NOTE: exercise_science is a VIEW over exercise_muscle. 0080 hit this exact
-- error and documented it; this migration then repeated it and took the API
-- down a second time. `test_no_migration_writes_to_a_view` now makes it
-- mechanically impossible rather than relying on anyone remembering.
UPDATE exercise_muscle
SET length_bias = 'mid',
    citation = 'schoenfeld-2021-ch8-program-design.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=schoenfeld-2021-ch8-program-design'
WHERE exercise_name IN ('Leg Extension', 'Seated Leg Curl');
