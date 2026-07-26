-- 0082: finish a drop 0080 missed, and key it on identity instead of a value
-- that 0080 itself was busy rewriting.
--
-- 0080 matched rows on (exercise_name, citation). `citation` is not an identity
-- — it is the column that migration was changing. Its re-grounding step ran
-- first and overwrote the citation; the later "drop the rows the vault
-- contradicts" step then looked for the OLD citation and found nothing. It also
-- omitted `muscle`, so an exercise with several curated rows could have one
-- row's verdict applied to its sibling.
--
-- Net effect: `Overhead Press (Dumbbell)`/side_delts and `Step Up
-- (Dumbbell)`/gluteus_medius dropped correctly, but `Arnold Press
-- (Dumbbell)`/side_delts kept a vault citation asserting a claim that same
-- vault note CONTRADICTS — ch8 records the shoulder press as primarily the
-- ANTERIOR head, and true middle-delt work as requiring an internally rotated
-- shoulder. A citation pointing at a note that refutes the row is worse than
-- the unverifiable paper it replaced: it reads as verified.
--
-- (exercise_name, muscle) is the row's identity. Strip the science, keep the
-- crediting — Arnold Press does involve the side delts, it is simply not a
-- side-delt BUILDER, so it should credit volume without being selectable as a
-- side-delt exercise.

UPDATE exercise_muscle
SET citation = NULL,
    citation_url = NULL,
    region = NULL,
    length_bias = NULL,
    rationale = NULL,
    sfr_tier = NULL
WHERE exercise_name = 'Arnold Press (Dumbbell)'
  AND muscle = 'side_delts';
