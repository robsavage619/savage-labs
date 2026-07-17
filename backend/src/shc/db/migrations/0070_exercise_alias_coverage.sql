-- Migration 0070: close confirmed gaps in the curated→logged alias bridge.
--
-- The 0070-era selection work (commits 3a879d5 + 86d3261) added a read-only
-- diagnostic (/api/training/alias-gaps) that lists curated exercise_science names
-- the plateau signal can't see — no exact log match, no alias. Rob confirmed the
-- three real same-movement pairs below on 2026-07-17; every other candidate the
-- token matcher surfaced was a FALSE PAIR and is deliberately left unmapped:
--   Decline/Incline Bench Press ≠ flat Barbell Bench Press
--   Front Squat (Barbell)       ≠ Squat (Barbell)
--   Romanian Deadlift (Barbell) ≠ Deadlift (Barbell)   (also a hip-hinge)
--   Glute Bridge (Barbell)      ≠ Glute Bridge March / Single Leg Glute Bridge
--   Hanging Leg Raise           ≠ Lying Leg Raise
--   Barbell Shrug               ≠ Hammerstrength Shrug  (different equipment)
--   Seated Calf Raise           ≠ Standing Calf Raise   (soleus vs gastroc)
-- The 19 genuinely un-performed movements (Chin-Up, Nordic Curl, Pull-Up, Skull
-- Crusher, …) correctly stay untried — no row here forces them.
--
-- Like 0067, these feed the progression/plateau lookup ONLY, never volume
-- crediting, so there is no double-count risk. Uses UPSERT (not DO NOTHING)
-- because 'Incline Curl (Dumbbell)' already had a 0067 alias to 'Incline Dumbbell
-- Curl' — a name Rob stopped logging in 2025-03 (he now logs the seated variant),
-- which made its long-head lead read "stale". Repointing it restores a live
-- plateau signal.

INSERT INTO exercise_alias (canonical_name, logged_name) VALUES
    ('Seated Calf Raise (Machine)', 'Seated Machine Calf Press'),
    ('Incline Curl (Dumbbell)',     'Seated Incline Curl (Dumbbell)'),
    ('Upright Row (Barbell)',       'Upright Row')
ON CONFLICT (canonical_name) DO UPDATE SET logged_name = excluded.logged_name;
