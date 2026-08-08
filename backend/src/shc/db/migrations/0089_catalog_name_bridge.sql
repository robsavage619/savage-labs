-- 0089: make the curated catalog speak the planner's vocabulary.
--
-- The planner is told to name exercises exactly as they appear in the Hevy
-- catalog, but 59 of 167 curated `exercise_science` names did not exist there.
-- Selection ranked them, rotated to them, and then the plan could not write
-- them — so the displaced staple stayed in and the same lifts recurred for
-- months (Face Pull and Lateral Raise on 23 of 49 training days). Four of the
-- seven rotations the engine actuated on 2026-08-08 named an unwritable lift.
--
-- Every pair below is one movement carrying two name conventions. The operation
-- is CLONE-THEN-RETIRE, never a rename:
--   1. the loggable survivor inherits the science (insert, or fill in a row that
--      carries no citation yet);
--   2. the duplicate's citation is cleared so it leaves the science menu.
-- The duplicate's `exercise_muscle` row SURVIVES with its role/credit intact, so
-- volume crediting for sets logged under the legacy name is untouched — several
-- of these carry four-figure Fitbod-era histories, and an in-place rename would
-- have silently orphaned them.
--
-- Pairs needing a real judgment call (equipment-ambiguous, or absent from Hevy
-- entirely) are deliberately NOT touched: an earlier fuzzy pass paired seated
-- with standing calf raises, and a chest fly with a rear-delt fly. Those stay
-- curated, are filtered from the menu at runtime by `loggable_names`, and are
-- reported by /api/training/alias-gaps.

-- Chin-Up  ->  Chin Up
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Chin Up', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Chin-Up' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Pull-Up  ->  Pull Up
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Pull Up', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Pull-Up' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dip (Chest)  ->  Chest Dip
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Chest Dip', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dip (Chest)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Close Grip Bench Press (Barbell)  ->  Bench Press - Close Grip (Barbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Bench Press - Close Grip (Barbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Close Grip Bench Press (Barbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Skull Crusher (Barbell)  ->  Skullcrusher (Barbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Skullcrusher (Barbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Skull Crusher (Barbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Barbell Hip Thrust  ->  Hip Thrust (Barbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Hip Thrust (Barbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Barbell Hip Thrust' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Cable Crossover Fly  ->  Cable Fly Crossovers
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Cable Fly Crossovers', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Cable Crossover Fly' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Bench Press  ->  Bench Press (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Bench Press (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Bench Press' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Bicep Curl  ->  Bicep Curl (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Bicep Curl (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Bicep Curl' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Front Raise  ->  Front Raise (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Front Raise (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Front Raise' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Incline Bench Press  ->  Incline Bench Press (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Incline Bench Press (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Incline Bench Press' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Shoulder Press  ->  Shoulder Press (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Shoulder Press (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Shoulder Press' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Kettlebell Sumo Squat  ->  Sumo Squat (Kettlebell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Sumo Squat (Kettlebell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Kettlebell Sumo Squat' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Machine Preacher Curl  ->  Preacher Curl (Machine)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Preacher Curl (Machine)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Machine Preacher Curl' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Overhead Tricep Extension (Cable)  ->  Overhead Triceps Extension (Cable)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Overhead Triceps Extension (Cable)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Overhead Tricep Extension (Cable)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Barbell Shrug  ->  Shrug (Barbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Shrug (Barbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Barbell Shrug' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dumbbell Shrug  ->  Shrug (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Shrug (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dumbbell Shrug' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Seated Tricep Press  ->  Seated Triceps Press
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Triceps Press', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Seated Tricep Press' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- T-Bar Row  ->  T Bar Row
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'T Bar Row', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'T-Bar Row' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Trap Bar Deadlift  ->  Deadlift (Trap bar)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Deadlift (Trap bar)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Trap Bar Deadlift' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Calf Raise (Machine)  ->  Standing Calf Raise (Machine)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Standing Calf Raise (Machine)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Calf Raise (Machine)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Leg Curl (Machine)  ->  Seated Leg Curl (Machine)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Leg Curl (Machine)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Leg Curl (Machine)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Cable Curl  ->  Cable Bicep Curl
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Cable Bicep Curl', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Cable Curl' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Concentration Curl (Dumbbell)  ->  Concentration Curl
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Concentration Curl', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Concentration Curl (Dumbbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Rear Delt Fly (Cable)  ->  Rear Delt Reverse Fly (Cable)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Rear Delt Reverse Fly (Cable)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Rear Delt Fly (Cable)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Rear Delt Fly (Dumbbell)  ->  Rear Delt Reverse Fly (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Rear Delt Reverse Fly (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Rear Delt Fly (Dumbbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Incline Curl (Dumbbell)  ->  Seated Incline Curl (Dumbbell)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Incline Curl (Dumbbell)', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Incline Curl (Dumbbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Pallof Press (Cable)  ->  Cable Core Pallof Press
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Cable Core Pallof Press', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Pallof Press (Cable)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Overhead Tricep Extension (Dumbbell)  ->  Dumbbell Tricep Extension
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Dumbbell Tricep Extension', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Overhead Tricep Extension (Dumbbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Single Arm Row (Dumbbell)  ->  Dumbbell Row
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Dumbbell Row', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Single Arm Row (Dumbbell)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Dip (Tricep)  ->  Machine Tricep Dip
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Machine Tricep Dip', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Dip (Tricep)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Seated Calf Raise (Machine)  ->  Seated Machine Calf Press
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Machine Calf Press', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Seated Calf Raise (Machine)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);
-- Tricep Pushdown (Cable)  ->  Cable Tricep Pushdown
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Cable Tricep Pushdown', muscle, role, credit, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Tricep Pushdown (Cable)' AND citation IS NOT NULL
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);

-- Retire every duplicate from the science view; crediting rows stay put.
UPDATE exercise_muscle SET citation = NULL, citation_url = NULL
  WHERE exercise_name IN (
    'Barbell Hip Thrust',
    'Barbell Shrug',
    'Cable Crossover Fly',
    'Cable Curl',
    'Calf Raise (Machine)',
    'Chin-Up',
    'Close Grip Bench Press (Barbell)',
    'Concentration Curl (Dumbbell)',
    'Dip (Chest)',
    'Dip (Tricep)',
    'Dumbbell Bench Press',
    'Dumbbell Bicep Curl',
    'Dumbbell Front Raise',
    'Dumbbell Incline Bench Press',
    'Dumbbell Shoulder Press',
    'Dumbbell Shrug',
    'Incline Curl (Dumbbell)',
    'Kettlebell Sumo Squat',
    'Leg Curl (Machine)',
    'Machine Preacher Curl',
    'Overhead Tricep Extension (Cable)',
    'Overhead Tricep Extension (Dumbbell)',
    'Pallof Press (Cable)',
    'Pull-Up',
    'Rear Delt Fly (Cable)',
    'Rear Delt Fly (Dumbbell)',
    'Seated Calf Raise (Machine)',
    'Seated Tricep Press',
    'Single Arm Row (Dumbbell)',
    'Skull Crusher (Barbell)',
    'T-Bar Row',
    'Trap Bar Deadlift',
    'Tricep Pushdown (Cable)'
  );

-- ── Abs is an emphasis muscle ─────────────────────────────────────────────
-- `muscle_emphasis` held only glutes and biceps, so abs ranked as an ordinary
-- grow-tier muscle and drew ~6 sets/wk — about one exercise per session against
-- a curated brief of 12-20 over 3x. The frozenset fallback in autoregulation.py
-- also listed traps, which this table has never contained; code and data now
-- agree (constant updated in the same change).
INSERT INTO muscle_emphasis (muscle, weight, note)
VALUES ('abs', 1.0, 'lagging bring-up — brief asks 12-20 sets/wk, was drawing ~2')
ON CONFLICT (muscle) DO UPDATE SET weight = EXCLUDED.weight, note = EXCLUDED.note;

-- ── Re-point the alias table at the surviving names ───────────────────────
-- `exercise_alias` maps a LOGGED string to the CURATED name (columns are
-- canonical_name, logged_name — that order). Volume crediting and the plateau
-- lookup both resolve through it, so a redirect aimed at a name this migration
-- retires would silently zero out region credit for the staple pointing at it.
--
-- The redirect is INVERTED rather than dropped: the survivor becomes the
-- canonical, and the retired duplicate becomes a logged alias of it. That keeps
-- crediting intact in BOTH directions — sets logged under the legacy Fitbod
-- string still credit the surviving science, which a plain DELETE would have
-- lost. canonical_name is the primary key and no survivor is claimed twice.
DELETE FROM exercise_alias WHERE canonical_name IN (
    'Barbell Hip Thrust',
    'Barbell Shrug',
    'Cable Crossover Fly',
    'Cable Curl',
    'Calf Raise (Machine)',
    'Chin-Up',
    'Close Grip Bench Press (Barbell)',
    'Concentration Curl (Dumbbell)',
    'Dip (Chest)',
    'Dip (Tricep)',
    'Dumbbell Bench Press',
    'Dumbbell Bicep Curl',
    'Dumbbell Front Raise',
    'Dumbbell Incline Bench Press',
    'Dumbbell Shoulder Press',
    'Dumbbell Shrug',
    'Incline Curl (Dumbbell)',
    'Kettlebell Sumo Squat',
    'Leg Curl (Machine)',
    'Machine Preacher Curl',
    'Overhead Tricep Extension (Cable)',
    'Overhead Tricep Extension (Dumbbell)',
    'Pallof Press (Cable)',
    'Pull-Up',
    'Rear Delt Fly (Cable)',
    'Rear Delt Fly (Dumbbell)',
    'Seated Calf Raise (Machine)',
    'Seated Tricep Press',
    'Single Arm Row (Dumbbell)',
    'Skull Crusher (Barbell)',
    'T-Bar Row',
    'Trap Bar Deadlift',
    'Tricep Pushdown (Cable)'
);

INSERT INTO exercise_alias (canonical_name, logged_name) VALUES
    ('Bench Press (Dumbbell)', 'Dumbbell Bench Press'),
    ('Bench Press - Close Grip (Barbell)', 'Close Grip Bench Press (Barbell)'),
    ('Bicep Curl (Dumbbell)', 'Dumbbell Bicep Curl'),
    ('Cable Bicep Curl', 'Cable Curl'),
    ('Cable Core Pallof Press', 'Pallof Press (Cable)'),
    ('Cable Fly Crossovers', 'Cable Crossover Fly'),
    ('Cable Tricep Pushdown', 'Tricep Pushdown (Cable)'),
    ('Chest Dip', 'Dip (Chest)'),
    ('Chin Up', 'Chin-Up'),
    ('Concentration Curl', 'Concentration Curl (Dumbbell)'),
    ('Deadlift (Trap bar)', 'Trap Bar Deadlift'),
    ('Dumbbell Row', 'Single Arm Row (Dumbbell)'),
    ('Dumbbell Tricep Extension', 'Overhead Tricep Extension (Dumbbell)'),
    ('Front Raise (Dumbbell)', 'Dumbbell Front Raise'),
    ('Hip Thrust (Barbell)', 'Barbell Hip Thrust'),
    ('Incline Bench Press (Dumbbell)', 'Dumbbell Incline Bench Press'),
    ('Machine Tricep Dip', 'Dip (Tricep)'),
    ('Overhead Triceps Extension (Cable)', 'Overhead Tricep Extension (Cable)'),
    ('Preacher Curl (Machine)', 'Machine Preacher Curl'),
    ('Pull Up', 'Pull-Up'),
    ('Rear Delt Reverse Fly (Cable)', 'Rear Delt Fly (Cable)'),
    ('Rear Delt Reverse Fly (Dumbbell)', 'Rear Delt Fly (Dumbbell)'),
    ('Seated Incline Curl (Dumbbell)', 'Incline Curl (Dumbbell)'),
    ('Seated Leg Curl (Machine)', 'Leg Curl (Machine)'),
    ('Seated Machine Calf Press', 'Seated Calf Raise (Machine)'),
    ('Seated Triceps Press', 'Seated Tricep Press'),
    ('Shoulder Press (Dumbbell)', 'Dumbbell Shoulder Press'),
    ('Shrug (Barbell)', 'Barbell Shrug'),
    ('Shrug (Dumbbell)', 'Dumbbell Shrug'),
    ('Skullcrusher (Barbell)', 'Skull Crusher (Barbell)'),
    ('Standing Calf Raise (Machine)', 'Calf Raise (Machine)'),
    ('Sumo Squat (Kettlebell)', 'Kettlebell Sumo Squat'),
    ('T Bar Row', 'T-Bar Row')
ON CONFLICT (canonical_name) DO UPDATE SET logged_name = EXCLUDED.logged_name;
