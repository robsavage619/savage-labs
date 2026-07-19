-- Migration 0067: bridge curated exercise_science names to Hevy's logged strings.
--
-- The curated science catalog and Hevy's logged exercise names use different
-- conventions ("Tricep Pushdown (Cable)" vs "Cable Tricep Pushdown"), so a set
-- logged under the variant name was invisible when scoring a curated exercise's
-- progression. That defeated the plateau-triggered rotation added alongside this
-- migration: a staple Rob has done hundreds of times read as "never trained", so
-- its stall was never seen and it was never swapped.
--
-- This table resolves each curated (canonical) name to the single logged string
-- Rob actually uses for the SAME movement + SAME equipment. Originally consumed
-- ONLY by the progression lookup in autoregulation._progress_ranks; as of the
-- 2026-07 engine remediation it ALSO resolves weekly_region_volume's join
-- (shc.training.volume), because leaving that join exact-match meant any
-- curated staple logged under its alias read zero region volume forever and
-- permanently led its head's rotation as "never trained" — see DECISIONS.md.
-- Safe: canonical_name is a PRIMARY KEY, so one logged name resolves to at most
-- one canonical name — no fan-out, no double-counting.
--
-- Mappings are hand-vetted, not fuzzy-matched: token matching produced dangerous
-- false pairs (e.g. "Rear Delt Fly (Dumbbell)" → "Dumbbell Fly", a CHEST fly), so
-- only unambiguous same-movement/same-equipment pairs are included. Genuinely
-- un-performed movements (Chin-Up, Nordic Curl, barbell bench variants Rob logs
-- only with dumbbells) are deliberately left unmapped — they correctly read as
-- untried.

CREATE TABLE IF NOT EXISTS exercise_alias (
    canonical_name TEXT PRIMARY KEY,  -- name as it appears in exercise_science
    logged_name    TEXT NOT NULL      -- the string Rob logs the same movement under
);

INSERT INTO exercise_alias (canonical_name, logged_name) VALUES
    ('Incline Curl (Dumbbell)',              'Incline Dumbbell Curl'),
    ('Tricep Pushdown (Cable)',              'Cable Tricep Pushdown'),
    ('Overhead Tricep Extension (Dumbbell)', 'Dumbbell Tricep Extension'),
    ('Overhead Tricep Extension (Cable)',    'Cable Rope Overhead Triceps Extension'),
    ('Cable Curl',                           'Cable Bicep Curl'),
    ('Concentration Curl (Dumbbell)',        'Concentration Curl'),
    ('Leg Curl (Machine)',                   'Seated Leg Curl (Machine)'),
    ('Bulgarian Split Squat (Dumbbell)',     'Bulgarian Split Squat'),
    ('Dip (Tricep)',                         'Machine Tricep Dip'),
    ('Step Up (Dumbbell)',                   'Dumbbell Step Up'),
    ('Pallof Press (Cable)',                 'Cable Core Pallof Press'),
    ('Seated Palms Up Wrist Curl',           'Palms-Up Dumbbell Wrist Curl'),
    ('Rear Delt Fly (Cable)',                'Rear Delt Reverse Fly (Cable)'),
    ('Rear Delt Fly (Dumbbell)',             'Rear Delt Reverse Fly (Dumbbell)'),
    ('Calf Raise (Machine)',                 'Standing Calf Raise (Machine)'),
    ('Single Arm Row (Dumbbell)',            'Dumbbell Row'),
    ('Overhead Press (Dumbbell)',            'Shoulder Press (Dumbbell)')
ON CONFLICT DO NOTHING;
