-- Migration 0057: the exercise-science evidence layer.
--
-- SHC's guiding light is sports science: every exercise, rep range, and the
-- frequency the engine prescribes must be defensible from the muscle-development
-- literature, with a citation. Until now exercise SELECTION had none — the menu
-- was a flat per-muscle list ordered by most-recently-performed. These two tables
-- encode the evidence so selection is driven by head/region coverage and
-- muscle-length bias, and every pick carries its rationale + source.
--
-- BICEPS is curated here as the worked template (pass 1). Every other muscle
-- group follows the same fully-cited standard in subsequent migrations; muscles
-- without a row fall back to the legacy recency menu until curated.

-- Per-exercise, evidence-tagged attributes.
CREATE TABLE IF NOT EXISTS exercise_science (
    exercise_name TEXT PRIMARY KEY,                  -- matches exercise_muscle_map.exercise_name
    muscle        TEXT NOT NULL,                     -- primary muscle this row characterizes
    region        TEXT,                              -- head/region emphasis (muscle-specific vocab)
    length_bias   TEXT NOT NULL,                     -- 'lengthened' | 'mid' | 'shortened'
    rep_low       INTEGER NOT NULL,
    rep_high      INTEGER NOT NULL,
    sfr_tier      TEXT NOT NULL DEFAULT 'moderate',  -- stimulus-to-fatigue: 'high'|'moderate'|'low'
    rationale     TEXT NOT NULL,                     -- the evidence-grounded WHY (shown to Rob)
    citation      TEXT NOT NULL,                     -- short ref (Author Year)
    citation_url  TEXT
);

-- Per-muscle programming evidence: coverage requirements, length priority, the
-- weekly set band, frequency, and rep scheme — each cited. Drives the coverage
-- target for selection and the scheduling/dosage rationale.
CREATE TABLE IF NOT EXISTS muscle_development (
    muscle           TEXT PRIMARY KEY,
    regions          TEXT NOT NULL,        -- JSON array of regions/heads to cover across the week
    length_priority  TEXT NOT NULL,        -- e.g. 'lengthened'
    weekly_sets_low  INTEGER NOT NULL,
    weekly_sets_high INTEGER NOT NULL,
    freq_per_week    INTEGER NOT NULL,
    rep_scheme       TEXT NOT NULL,
    rationale        TEXT NOT NULL,
    citation         TEXT NOT NULL,
    citation_url     TEXT
);

-- ── BICEPS development brief ─────────────────────────────────────────────────
INSERT INTO muscle_development
    (muscle, regions, length_priority, weekly_sets_low, weekly_sets_high,
     freq_per_week, rep_scheme, rationale, citation, citation_url)
VALUES (
    'biceps',
    '["long_head","short_head","brachialis"]',
    'lengthened',
    12, 20, 2,
    'Bulk of sets 8–15 reps taken to 0–2 RIR; include lighter (12–20) lengthened isolation for the stretch stimulus and heavier (6–10) loadable curls. All heads covered across the week.',
    'Lengthened-position bias for hypertrophy (Zabaleta-Korta 2023; Wolf 2025 review). 12–20 direct sets/wk is the dose-response sweet spot (Baz-Valle 2022); benefit rises with volume but with diminishing returns and frequency secondary to total volume (Pelland 2025; Heaselgrave 2019). Load is permissive 6–25 reps near failure (Schoenfeld 2015); failure itself not required (Sampson 2016).',
    'Baz-Valle 2022 / Zabaleta-Korta 2023',
    'https://consensus.app/papers/details/d82bc2b70af65cea97f69cdebc6ab92a/'
)
ON CONFLICT DO NOTHING;

-- ── BICEPS exercise science ──────────────────────────────────────────────────
-- length_bias reflects where peak tension lands in the ROM; region is the head
-- emphasized. Long head is maximally stretched by shoulder EXTENSION (incline /
-- behind-body), short head by the preacher/flexed-shoulder position, brachialis
-- by a neutral/pronated grip.
INSERT INTO exercise_science
    (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
    ('Incline Curl (Dumbbell)', 'biceps', 'long_head', 'lengthened', 10, 20, 'high',
     'Shoulder extension stretches the long head under load and trains the biceps through the full ROM — the lengthened stimulus most associated with growth. Lead movement.',
     'Oliveira 2009 / Iwane 2023', 'https://consensus.app/papers/details/ec67ab4d4c4153f388b4cfd1e4ed6ef3/'),
    ('Preacher Curl (Barbell)', 'biceps', 'short_head', 'lengthened', 8, 12, 'moderate',
     'Barbell preacher loads the bottom (stretched) position hardest; the distal biceps grew in response to that stretch strain. Heavier-loadable short-head work.',
     'Zabaleta-Korta 2023 / Nunes 2020', 'https://consensus.app/papers/details/d67a1af1562b5444b9492b45567021ca/'),
    ('Hammer Curl (Dumbbell)', 'biceps', 'brachialis', 'mid', 10, 15, 'high',
     'Neutral grip shifts load to the brachialis/brachioradialis — building these adds arm thickness and the separation that reads as definition.',
     'Schoenfeld 2015', 'https://consensus.app/papers/details/6593367d67e9579ea60309060332f3ff/'),
    ('Bicep Curl (Barbell)', 'biceps', 'short_head', 'mid', 6, 12, 'moderate',
     'Supinated whole-ROM curl, the most loadable — anchors the heavier end of the rep range for progressive overload.',
     'Schoenfeld 2015', 'https://consensus.app/papers/details/6593367d67e9579ea60309060332f3ff/'),
    ('Bicep Curl (Dumbbell)', 'biceps', 'short_head', 'mid', 8, 15, 'moderate',
     'Supinating dumbbell curl through the full ROM; allows full supination for short-head emphasis.',
     'Oliveira 2009', 'https://consensus.app/papers/details/ec67ab4d4c4153f388b4cfd1e4ed6ef3/'),
    ('Cable Curl', 'biceps', 'short_head', 'mid', 10, 15, 'moderate',
     'Constant tension across the ROM (no slack at the bottom or top) — useful for higher-rep accumulation sets.',
     'Nunes 2020', 'https://consensus.app/papers/details/93268653115d5abf954b8da2fdaf41bb/'),
    ('Bicep Curl (Cable)', 'biceps', 'short_head', 'mid', 10, 15, 'moderate',
     'Constant-tension cable curl; interchangeable with Cable Curl for accumulation volume.',
     'Nunes 2020', 'https://consensus.app/papers/details/93268653115d5abf954b8da2fdaf41bb/'),
    ('Preacher Curl (Dumbbell)', 'biceps', 'short_head', 'shortened', 10, 15, 'moderate',
     'Dumbbell preacher peaks tension in the shorter/flexed range — a shortened-biased complement, not a substitute for stretch work.',
     'Oliveira 2009', 'https://consensus.app/papers/details/ec67ab4d4c4153f388b4cfd1e4ed6ef3/'),
    ('Concentration Curl (Dumbbell)', 'biceps', 'short_head', 'shortened', 12, 20, 'moderate',
     'Peak-contraction short-head work; high mind-muscle isolation for finishing higher-rep volume.',
     'Oliveira 2009', 'https://consensus.app/papers/details/ec67ab4d4c4153f388b4cfd1e4ed6ef3/')
ON CONFLICT DO NOTHING;
