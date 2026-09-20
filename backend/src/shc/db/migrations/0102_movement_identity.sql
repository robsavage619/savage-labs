-- Movement identity for the deduplicated set ledger.
--
-- PROBLEM. Rob's Fitbod history was imported into Hevy, so the SAME physical
-- session exists twice in `workout_sets` -- same day, same reps, same weight to
-- five decimals -- under two different exercise names:
--
--     hevy    Cable Fly Crossovers  4x6 @ 61.235kg
--     fitbod  Cable Crossover Fly   4x6 @ 61.23497000135107kg
--
-- `workout_sets_dedup` already elects one source per (day, canonical exercise),
-- but its canonical key only stripped a trailing parenthetical, so it matched
-- exactly 1 of 17 real twin pairs. 27% of all-time sets and 21% of the last
-- 365d survived as duplicates. Rolling 7d/28d windows were unaffected (no
-- Fitbod rows since 2026-04-22), but `fit_volume_landmarks` looks back 104
-- weeks, so every fitted MEV/MAV/MRV was built on inflated input -- chest +57%,
-- front_delts +53%, adductors +50%.
--
-- FIX, in two complementary parts, because neither alone is sufficient:
--
--   1. A stronger canonical key: strip the trailing parenthetical, lowercase,
--      drop punctuation, singularize each token, then SORT the tokens. This
--      catches the punctuation / word-order / plural family
--      ("T-Bar Row" = "T Bar Row", "Hammer Curls" = "Hammer Curl (Dumbbell)").
--      It does NOT reach a pair whose equipment word is a PREFIX on one side
--      and a trailing parenthetical on the other -- "Dumbbell Shrug" keys as
--      "dumbbell shrug" but "Shrug (Dumbbell)" keys as "shrug", because the
--      parenthetical is stripped before tokenizing. Those go in the twin map.
--
--   2. `exercise_source_twin`, below, for the word-choice renames no string
--      normalizer can reach ("Low Cable Chest Fly" = "Low Cable Fly
--      Crossovers"). Every row was DERIVED FROM EVIDENCE, not from string
--      similarity: the two names were logged on the same day with an identical
--      full set sequence (same multiset of (reps, weight) to 0.1kg, >=2 sets).
--      `evidence_days` / `evidence_sets` record how often, and `coverage` what
--      share of that legacy name's days the pairing explains.
--
-- WHY A COLLISION IS SAFE. The view filters on `chosen_source`, not on name, so
-- when two names collide into one canonical group they are BOTH kept whenever
-- they share a source. Two Hevy lifts colliding (e.g. "Cable Twist (Down to
-- up)" and "Cable Twist (Up to down)", which token-sort together) therefore
-- lose nothing. Only a collision that SPANS sources can drop a row, and that is
-- precisely the duplicate case this migration exists to drop.
--
-- MEASURED RESULT. Residual duplication 29.1% -> 3.8% all-time and 23.6% ->
-- 3.6% over 365d. 15,243 of the 15,382 removed work-sets have a confirmed Hevy
-- counterpart with matching (reps, weight) on the same day. The remaining 139
-- are real losses from partial-overlap days where Fitbod logged more sets than
-- Hevy; 131 of those fall in 2017-2020 and only 8 land inside the 104-week
-- landmark window, which is why source election is kept rather than replaced
-- with a row-level anti-join.
--
-- NOT INCLUDED, needs a human call -- the detector disagreed with an existing
-- `exercise_alias` row, or the evidence was thin:
--   Seated Machine Calf Press            detector: Calf Press (Machine)   alias: Seated Calf Raise
--   Cable Bicep Curl                     detector: Bicep Curl (Cable)     alias: Cable Curl
--   Cable Rope Overhead Triceps Extension detector: Triceps Rope Pushdown alias: Overhead Tricep Extension (Cable)
--   Seated Tricep Press                  detector: Dumbbell Tricep Extension (67d but only 32% coverage;
--                                        a seated press is not a dumbbell extension)
-- `exercise_source_twin` is deliberately a SEPARATE table from `exercise_alias`:
-- that table already carries two opposed meanings for its two consumers, and a
-- third would make it unreadable.

CREATE TABLE IF NOT EXISTS exercise_source_twin (
    legacy_name    VARCHAR PRIMARY KEY,
    current_name   VARCHAR NOT NULL,
    evidence_days  INTEGER NOT NULL,
    evidence_sets  INTEGER NOT NULL,
    coverage       DOUBLE  NOT NULL
);

DELETE FROM exercise_source_twin;
INSERT INTO exercise_source_twin (legacy_name, current_name, evidence_days, evidence_sets, coverage) VALUES
    ('Air Squats', 'Squat (Bodyweight)', 29, 102, 0.64),
    ('Barbell Hip Thrust', 'Hip Thrust (Barbell)', 33, 141, 0.89),
    ('Cable Crossover Fly', 'Cable Fly Crossovers', 113, 448, 0.82),
    ('Cable Lateral Raise', 'Lateral Raise (Cable)', 12, 46, 0.86),
    ('Cable Rope Tricep Extension', 'Triceps Rope Pushdown', 45, 183, 0.61),
    ('Cable Row', 'Seated Cable Row - Bar Grip', 81, 330, 0.57),
    ('Cable Tricep Extension', 'Cable Tricep Pushdown', 15, 56, 0.71),
    ('Cable Upright Row', 'Upright Row (Cable)', 10, 38, 0.38),
    ('Crunches', 'Crunch', 172, 663, 0.8),
    ('Dumbbell Bench Press', 'Bench Press (Dumbbell)', 29, 112, 0.22),
    ('Dumbbell Bicep Curl', 'Bicep Curl (Dumbbell)', 116, 462, 0.65),
    ('Dumbbell Fly', 'Chest Fly (Dumbbell)', 71, 287, 0.34),
    ('Dumbbell Front Raise', 'Front Raise (Dumbbell)', 135, 544, 0.88),
    ('Dumbbell Goblet Squat', 'Goblet Squat', 22, 67, 1.0),
    ('Dumbbell Incline Bench Press', 'Incline Bench Press (Dumbbell)', 41, 164, 0.34),
    ('Dumbbell Shoulder Press', 'Shoulder Press (Dumbbell)', 70, 281, 0.32),
    ('Dumbbell Shrug', 'Shrug (Dumbbell)', 197, 807, 0.88),
    ('Hack Squat', 'Hack Squat (Machine)', 35, 147, 0.81),
    ('Hammer Curls', 'Hammer Curl (Dumbbell)', 111, 456, 0.39),
    ('Hammerstrength Iso Row', 'Iso-Lateral Row (Machine)', 46, 183, 0.59),
    ('Kettlebell Front Squat', 'Goblet Squat', 6, 22, 1.0),
    ('Kettlebell Sumo Squat', 'Sumo Squat (Kettlebell)', 32, 140, 0.8),
    ('Lat Pulldown', 'Lat Pulldown (Cable)', 18, 67, 0.2),
    ('Leg Curl', 'Lying Leg Curl (Machine)', 13, 54, 0.43),
    ('Leg Extension', 'Leg Extension (Machine)', 81, 320, 0.63),
    ('Leg Press', 'Leg Press (Machine)', 48, 188, 0.62),
    ('Low Cable Chest Fly', 'Low Cable Fly Crossovers', 17, 67, 0.94),
    ('Lying Hamstrings Curl', 'Lying Leg Curl (Machine)', 21, 83, 0.46),
    ('Machine Hip Abductor', 'Hip Abduction (Machine)', 7, 28, 0.88),
    ('Machine Hip Adductor', 'Hip Adduction (Machine)', 56, 231, 1.0),
    ('Machine Lateral Raise', 'Lateral Raise (Machine)', 29, 117, 0.94),
    ('Machine Overhead Press', 'Seated Shoulder Press (Machine)', 64, 253, 0.97),
    ('Machine Preacher Curl', 'Preacher Curl (Machine)', 126, 497, 0.84),
    ('Machine Shoulder Press', 'Seated Shoulder Press (Machine)', 81, 315, 0.78),
    ('Machine Thigh Adductor', 'Hip Adduction (Machine)', 41, 169, 1.0),
    ('Seated Leg Curl', 'Seated Leg Curl (Machine)', 33, 135, 0.56),
    ('Smith Machine Overhead Shoulder Press', 'Overhead Press (Smith Machine)', 12, 48, 0.48);

CREATE OR REPLACE VIEW workout_sets_dedup AS
WITH labeled AS (
    SELECT
        ws.id,
        ws.workout_id,
        ws.exercise,
        ws.set_idx,
        ws.reps,
        ws.weight_kg,
        ws.rpe,
        ws.is_warmup,
        ws.content_hash,
        w.source,
        w.started_at,
        w.started_at::DATE AS day_d,
        -- Twin-map first (legacy name -> the name Rob logs it under today),
        -- then normalize. Order matters: the map is keyed on the raw string.
        array_to_string(
            list_sort(list_transform(
                string_split_regex(
                    regexp_replace(
                        lower(trim(regexp_replace(
                            COALESCE(t.current_name, ws.exercise), '\s*\([^)]*\)\s*$', ''))),
                        '[^a-z0-9 ]', ' ', 'g'),
                    '\s+'),
                tok -> CASE WHEN length(tok) > 3 AND ends_with(tok, 's')
                            THEN tok[1:length(tok) - 1] ELSE tok END)),
            ' ') AS canon_exercise
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    LEFT JOIN exercise_source_twin t ON t.legacy_name = ws.exercise
),
best_source AS (
    SELECT
        day_d,
        canon_exercise,
        CASE
            WHEN COUNT(*) FILTER (WHERE source = 'hevy') > 0 THEN 'hevy'
            WHEN COUNT(*) FILTER (WHERE source = 'fitbod') > 0 THEN 'fitbod'
            ELSE MIN(source)
        END AS chosen_source
    FROM labeled
    GROUP BY day_d, canon_exercise
)
SELECT l.*
FROM labeled l
JOIN best_source b
  ON b.day_d = l.day_d
 AND b.canon_exercise = l.canon_exercise
 AND b.chosen_source = l.source;
