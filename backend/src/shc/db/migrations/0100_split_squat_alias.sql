-- Migration 0100: bridge the curated Bulgarian Split Squat to the name Rob logs it under.
--
-- The curated row 'Bulgarian Split Squat (Dumbbell)' had 2 logged sets in 180 days
-- (last 2026-07-31) while the uncurated 'Split Squat (Dumbbell)' carried 31 (last
-- 2026-09-17) at the same 45 lb/hand. With no bridge the menu read the curated lift
-- as "young, last 2026-07-31" and the planner re-prescribed it two days after Rob
-- had split-squatted, and this week's quad heads read vastii 0 despite that session.
--
-- alias_gap_report misses this shape: it only flags a curated name with NO logged
-- history, and two stray sets under the curated string made it read as resolved.
-- A 180-day sweep for "curated name shadowed by a busier same-equipment synonym"
-- found this as the only real pair; the other hits were false pairs (single-leg vs
-- bilateral RDL, straight-arm vs standard pulldown, reverse vs standard curl).
--
-- _progress_info prefers whichever name was trained most recently, so the two
-- sets logged under the curated string stay readable.

INSERT INTO exercise_alias (canonical_name, logged_name) VALUES
    ('Bulgarian Split Squat (Dumbbell)', 'Split Squat (Dumbbell)')
ON CONFLICT (canonical_name) DO UPDATE SET logged_name = excluded.logged_name;
