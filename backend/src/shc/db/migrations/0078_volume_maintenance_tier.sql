-- 0078: the fourth volume landmark (MV) + an explicit per-muscle training tier.
--
-- The engine implemented 3 of the 4 landmarks its own cited source defines
-- (volume-landmarks-mev-mav-mrv.md: "MV (Maintenance Volume, ~1-2 hard
-- sets/muscle/week), MEV, MAV, MRV"). With no MV tier every muscle was a
-- growth target every week: the sum of MEV across 17 muscles is 137
-- muscle-sets/wk against a measured delivery of ~94 (63.5 working sets median
-- x 1.48 primary+secondary credit), so 16 of 17 muscles reported "below MEV"
-- permanently and all 17 emitted ADD. An unsatisfiable, unranked demand list
-- forces the planner to triage silently -- which it did, toward whatever
-- compounds were already habitual.
--
-- tier is DELIBERATELY explicit and human-set, never fitted or inferred.
-- Invariant 6 forbids a *fitted* personal band tightening a growth gate below
-- the population floor; dropping a muscle from MEV to MV is exactly that shape,
-- and is only legitimate as a stated training intent. Absence of a tier reads
-- as 'grow' everywhere downstream, so a missing migration or a failed read can
-- never silently under-train.

ALTER TABLE muscle_volume_targets ADD COLUMN IF NOT EXISTS mv_sets INTEGER;
ALTER TABLE muscle_volume_targets ADD COLUMN IF NOT EXISTS tier TEXT;

-- MV = 2 sets/muscle/wk: the top of the vault's 1-2 range. The conservative
-- choice is the HIGHER one -- maintenance exists to protect accrued size, and
-- erring low is the under-training failure this whole change is meant to fix.
UPDATE muscle_volume_targets SET mv_sets = 2 WHERE mv_sets IS NULL;

-- Default every muscle to 'grow' -- identical behaviour to pre-0078 -- then
-- name the maintenance set explicitly below. Nothing is demoted by omission.
UPDATE muscle_volume_targets SET tier = 'grow' WHERE tier IS NULL;

-- This mesocycle's priority set: Rob's two stated emphasis bring-ups
-- (biceps, glutes) plus the three largest compound-led growth drivers
-- (chest, lats, quads). Everything else holds at MV, where the vault records
-- 1-2 hard sets/wk maintaining hypertrophy for up to ~3 months in trained
-- lifters -- so this costs no accrued size, it reallocates the weekly budget.
UPDATE muscle_volume_targets
SET tier = 'maintain'
WHERE muscle_group NOT IN ('biceps', 'glutes', 'chest', 'lats', 'quads');

-- An emphasis muscle must never sit at maintenance (invariant 7: conditioning
-- interference may not freeze an emphasis muscle below MEV -- demoting it to MV
-- by tier would be the same silent under-train through a different door).
UPDATE muscle_volume_targets
SET tier = 'grow'
WHERE muscle_group IN (SELECT muscle FROM muscle_emphasis);
