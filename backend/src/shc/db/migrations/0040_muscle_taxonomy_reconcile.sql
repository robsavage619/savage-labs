-- Migration 0040: reconcile the per-muscle volume taxonomy to ONE canonical
-- anatomical vocabulary, and make muscle_volume_targets actually join to it.
--
-- THE BUG THIS FIXES:
--   muscle_volume_targets was keyed by movement pattern (push/pull/legs/arms/
--   shoulders/core), while actual sets are counted by anatomical muscle via
--   exercise_muscle_map.primary_muscle (biceps/glutes/chest/...). The keys never
--   joined — every /api/training/muscle-volume row was either count-with-no-target
--   or target-with-no-count, and biceps + glutes had no target at all.
--
-- CANONICAL VOCABULARY (aligned with the frontend BodyDiagram / daily_checkin
-- soreness region keys, so the Phase-2 controller can read recovery per muscle):
--   chest, front_delts, side_delts, rear_delts, triceps, biceps, forearms,
--   lats, mid_back, traps, lower_back, quads, hamstrings, glutes, adductors,
--   calves, abs
--
-- The exercise_muscle_map was seeded inconsistently across 0025 ('back'), 0036
-- ('lats'/'mid_back') and the dynamic Hevy join in 0038 (raw Hevy groups like
-- 'shoulders', 'upper_back', 'quadriceps', 'abdominals', 'abductors'). Normalize
-- both primary_muscle and the secondary_muscles[] array to the canonical set.

-- ── 1. Normalize primary_muscle to canonical ────────────────────────────────
UPDATE exercise_muscle_map SET primary_muscle = CASE primary_muscle
    WHEN 'back'          THEN 'lats'         -- legacy 0025 coarse key
    WHEN 'upper_back'    THEN 'mid_back'     -- Hevy
    WHEN 'quadriceps'    THEN 'quads'        -- Hevy
    WHEN 'abdominals'    THEN 'abs'          -- Hevy
    WHEN 'abductors'     THEN 'glutes'       -- hip abduction = glute medius
    WHEN 'shoulders'     THEN 'side_delts'   -- Hevy generic delt bucket
    ELSE primary_muscle
END
WHERE primary_muscle IN
    ('back', 'upper_back', 'quadriceps', 'abdominals', 'abductors', 'shoulders');

-- ── 2. Normalize the secondary_muscles[] array element-wise ──────────────────
UPDATE exercise_muscle_map
SET secondary_muscles = list_transform(secondary_muscles, x -> CASE x
    WHEN 'back'       THEN 'lats'
    WHEN 'upper_back' THEN 'mid_back'
    WHEN 'quadriceps' THEN 'quads'
    WHEN 'abdominals' THEN 'abs'
    WHEN 'abductors'  THEN 'glutes'
    WHEN 'shoulders'  THEN 'side_delts'
    ELSE x
END)
WHERE len(secondary_muscles) > 0;

-- ── 3. Drop the orphaned movement-pattern targets ───────────────────────────
-- These never joined to anatomical actuals. Replaced by canonical rows below.
DELETE FROM muscle_volume_targets
WHERE muscle_group IN ('push', 'pull', 'legs', 'arms', 'shoulders', 'core');

-- ── 4. Seed canonical per-muscle MEV/MAV/MRV landmarks (global defaults) ─────
-- Weekly DIRECT working-set landmarks, Renaissance Periodization norms (Israetel).
-- '' mesocycle_id = global default; Phase 3 writes mesocycle-scoped overrides
-- as Rob's individual dose-response is fitted. biceps + glutes are first-class
-- here — the previously-missing targets.
INSERT OR IGNORE INTO muscle_volume_targets
    (muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id) VALUES
    ('chest',      10, 16, 22, ''),
    ('front_delts', 6, 12, 18, ''),
    ('side_delts',  8, 16, 22, ''),
    ('rear_delts',  8, 16, 22, ''),
    ('triceps',     6, 12, 18, ''),
    ('biceps',      8, 14, 20, ''),
    ('forearms',    4,  8, 12, ''),
    ('lats',       10, 16, 20, ''),
    ('mid_back',    8, 14, 22, ''),
    ('traps',       4,  8, 16, ''),
    ('lower_back',  4,  8, 12, ''),
    ('quads',       8, 14, 20, ''),
    ('hamstrings',  6, 12, 18, ''),
    ('glutes',      6, 12, 16, ''),
    ('adductors',   4,  8, 12, ''),
    ('calves',      8, 14, 20, ''),
    ('abs',         6, 12, 20, '');
