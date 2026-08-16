-- 0096: give every neutral-grip curl the forearms credit the catalog already
-- grants to two of them.
--
-- Migration 0065 credited forearms at 0.3 on `Hammer Curl (Dumbbell)` and
-- `Hammer Curls`, on the ground that a neutral grip makes the brachioradialis a
-- prime mover. It listed those two names and nothing else, so the other hammer
-- variants Rob actually logs credit forearms zero: Cable Rope Hammer Curls (121
-- sets), Incline Hammer Curl (185), Seated Hammer Curls (44), Loop Band Hammer
-- Curl (5). Forearms currently draws 100% of its volume from indirect credit and
-- reads 3.3 sets over 28 days off a single exercise, so the gap is most of the
-- ledger for that muscle.
--
-- This is a NAME-VARIANT gap, not new science — the same class of hole 0064 and
-- 0065 were written to close. The rows are copied from the existing
-- `Hammer Curl (Dumbbell)` row rather than hand-written, so rate, region and
-- citation stay identical to the vetted original.
--
-- Deliberately NOT extended to supinated curls (Bicep Curl (Cable), Barbell
-- Bicep Drag Curl, Seated Incline Curl (Dumbbell), and ~30 others). Their
-- absence looked like a gap on first pass but is the catalog's consistent
-- convention: NO supinated curl anywhere credits forearms, and only neutral or
-- pronated grips do. Changing that is a science decision, not a data repair.
--
-- Also NOT included: `Reverse Barbell Curl`, which classifies biceps-primary
-- while the identical movement under the name `Reverse Curl (Barbell)`
-- classifies forearms-primary. Flipping a PRIMARY rewrites biceps history, and
-- at 4 logged sets the churn is not worth it inside a data-repair migration.

INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT v.name, m.muscle, m.role, m.credit, m.region, m.length_bias, m.rep_low, m.rep_high,
       m.sfr_tier, m.rationale, m.citation, m.citation_url
  FROM exercise_muscle m
  CROSS JOIN (VALUES ('Cable Rope Hammer Curls'),
                     ('Incline Hammer Curl'),
                     ('Seated Hammer Curls'),
                     ('Loop Band Hammer Curl')) AS v(name)
 WHERE m.exercise_name = 'Hammer Curl (Dumbbell)'
   AND m.muscle = 'forearms'
   AND m.role = 'secondary'
ON CONFLICT (exercise_name, muscle) DO NOTHING;
