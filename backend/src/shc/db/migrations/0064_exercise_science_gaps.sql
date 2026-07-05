-- Migration 0064: curate the frequently-trained exercises that still fell to
-- the recency fallback (had an exercise_muscle_map row but no exercise_science
-- row, so selection couldn't reason about head/length/SFR for them).
--
-- Every row here is COPIED from an already-vetted canonical row via INSERT..SELECT
-- rather than hand-authored: each of these movements is a naming variant or a
-- machine/cable equivalent of a movement 0057-0060 already grounded with a real
-- citation, so the honest thing is to inherit that vetted citation + region +
-- length-bias + rep range, not invent new science. The source is chosen to match
-- the variant's actual mechanics (e.g. a low-to-high cable fly inherits the
-- UPPER-chest incline-fly row, not the mid-chest one). Multi-head movements get
-- one INSERT per canonical (muscle) row, so a movement like Hammer Curls inherits
-- both its brachialis (biceps) and brachioradialis (forearms) rows.
--
-- Each SELECT is `'<variant>', muscle, region, length_bias, rep_low, rep_high,
-- sfr_tier, rationale, citation, citation_url` — the literal variant name plus the
-- canonical's other nine columns, matching the table's column order exactly.
--
-- Scoped to the ~15 movements Rob actually trains often; the long tail of
-- duplicate/legacy names is intentionally left to the fallback.
--
-- Catalog first: every science-curated exercise MUST also carry an
-- exercise_muscle_map row (engine invariant — a pickable movement has to be in
-- the catalog). These already exist in Rob's Hevy-synced catalog, so ON CONFLICT
-- DO NOTHING makes this a no-op there; it only populates a fresh/migration-only
-- DB. primary_muscle matches the exercise_science muscle so volume crediting and
-- the science layer agree.
INSERT INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles) VALUES
    ('Hammerstrength Incline Chest Press', 'chest', ['front_delts', 'triceps']),
    ('Hammerstrength Shoulder Press', 'front_delts', ['triceps', 'side_delts']),
    ('Seated Dumbbell Curl', 'biceps', []),
    ('Hammer Curls', 'biceps', []),
    ('Triceps Rope Pushdown', 'triceps', []),
    ('Machine Tricep Dip', 'triceps', ['chest', 'front_delts']),
    ('Overhead Triceps Extension (Cable)', 'triceps', []),
    ('Cable Rope Overhead Triceps Extension', 'triceps', []),
    ('Cable Fly Crossovers', 'chest', ['front_delts']),
    ('Cable Crossover Fly', 'chest', ['front_delts']),
    ('Low Cable Fly Crossovers', 'chest', ['front_delts']),
    ('Low Cable Chest Fly', 'chest', ['front_delts']),
    ('Standing Machine Calf Press', 'calves', []),
    ('Seated Leg Curl (Machine)', 'hamstrings', []),
    ('Iso-Lateral Row (Machine)', 'lats', ['mid_back', 'biceps'])
ON CONFLICT DO NOTHING;

-- ── Chest presses / flyes ────────────────────────────────────────────────────
-- Machine incline press → inherits BOTH canonical rows (upper chest + front delts).
INSERT INTO exercise_science
SELECT 'Hammerstrength Incline Chest Press', muscle, region, length_bias, rep_low,
       rep_high, sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Incline Bench Press (Barbell)'
ON CONFLICT DO NOTHING;

-- Standard-height cable crossovers → mid-chest lengthened fly.
INSERT INTO exercise_science
SELECT 'Cable Fly Crossovers', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Chest Fly (Dumbbell)' AND muscle='chest'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_science
SELECT 'Cable Crossover Fly', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Chest Fly (Dumbbell)' AND muscle='chest'
ON CONFLICT DO NOTHING;

-- Low-to-high cable flyes bias the UPPER (clavicular) chest → inherit incline fly.
INSERT INTO exercise_science
SELECT 'Low Cable Fly Crossovers', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Incline Chest Fly (Dumbbell)' AND muscle='chest'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_science
SELECT 'Low Cable Chest Fly', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Incline Chest Fly (Dumbbell)' AND muscle='chest'
ON CONFLICT DO NOTHING;

-- ── Shoulders ────────────────────────────────────────────────────────────────
INSERT INTO exercise_science
SELECT 'Hammerstrength Shoulder Press', muscle, region, length_bias, rep_low,
       rep_high, sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Overhead Press (Barbell)' AND muscle='front_delts'
ON CONFLICT DO NOTHING;

-- ── Biceps / forearms ────────────────────────────────────────────────────────
-- Seated DB curl = a dumbbell curl → short head.
INSERT INTO exercise_science
SELECT 'Seated Dumbbell Curl', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Bicep Curl (Dumbbell)' AND muscle='biceps'
ON CONFLICT DO NOTHING;

-- "Hammer Curls" (Fitbod name) = Hammer Curl (Dumbbell): brachialis + brachioradialis.
INSERT INTO exercise_science
SELECT 'Hammer Curls', muscle, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Hammer Curl (Dumbbell)'
ON CONFLICT DO NOTHING;

-- ── Triceps ──────────────────────────────────────────────────────────────────
-- Rope pushdown = cable pushdown → lateral head, shortened.
INSERT INTO exercise_science
SELECT 'Triceps Rope Pushdown', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Tricep Pushdown (Cable)' AND muscle='triceps'
ON CONFLICT DO NOTHING;

-- Machine dip → lateral head (mirrors the tricep dip).
INSERT INTO exercise_science
SELECT 'Machine Tricep Dip', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Dip (Tricep)' AND muscle='triceps'
ON CONFLICT DO NOTHING;

-- Overhead cable/rope extensions (naming variants) → long head, lengthened.
INSERT INTO exercise_science
SELECT 'Overhead Triceps Extension (Cable)', muscle, region, length_bias, rep_low,
       rep_high, sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Overhead Tricep Extension (Cable)' AND muscle='triceps'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_science
SELECT 'Cable Rope Overhead Triceps Extension', muscle, region, length_bias, rep_low,
       rep_high, sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Overhead Tricep Extension (Cable)' AND muscle='triceps'
ON CONFLICT DO NOTHING;

-- ── Hamstrings / calves ──────────────────────────────────────────────────────
INSERT INTO exercise_science
SELECT 'Seated Leg Curl (Machine)', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Leg Curl (Machine)' AND muscle='hamstrings'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_science
SELECT 'Standing Machine Calf Press', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Calf Raise (Machine)' AND muscle='calves'
ON CONFLICT DO NOTHING;

-- ── Back ─────────────────────────────────────────────────────────────────────
-- Iso-lateral machine row → lats (like a single-arm row) + mid-back rhomboids.
INSERT INTO exercise_science
SELECT 'Iso-Lateral Row (Machine)', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='Single Arm Row (Dumbbell)' AND muscle='lats'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_science
SELECT 'Iso-Lateral Row (Machine)', muscle, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
FROM exercise_science WHERE exercise_name='T-Bar Row' AND muscle='mid_back'
ON CONFLICT DO NOTHING;
