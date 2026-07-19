-- Personal research lab — pre-registered hypotheses + test results.
-- Tight scope: a fixed catalogue of statistical questions runs against the
-- DuckDB time-series weekly. Each finding writes to lab_findings with a
-- confirmed/refuted/insufficient verdict + effect size + n. Vault entries
-- supply the methodology references.

CREATE TABLE IF NOT EXISTS lab_questions (
    id           VARCHAR PRIMARY KEY,        -- stable slug ('sleep_short_hrv_drop')
    title        VARCHAR NOT NULL,           -- one-line human-readable
    hypothesis   VARCHAR NOT NULL,           -- precise predicate
    exposure     VARCHAR NOT NULL,           -- e.g. 'sleep_hours < 6.5'
    outcome      VARCHAR NOT NULL,           -- e.g. 'next_day_hrv'
    test_type    VARCHAR NOT NULL,           -- 'paired_t' | 'wilcoxon' | 'correlation' | 'change_point'
    window_days  INTEGER NOT NULL DEFAULT 90,
    min_n        INTEGER NOT NULL DEFAULT 14, -- minimum observations to run
    threshold    DOUBLE,                       -- effect-size cutoff for 'confirmed'
    direction    VARCHAR,                      -- 'positive' | 'negative' | 'either'
    vault_ref    VARCHAR,                      -- pointer into the vault
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lab_findings (
    id           VARCHAR PRIMARY KEY,        -- uuid
    question_id  VARCHAR NOT NULL REFERENCES lab_questions(id),
    run_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    n            INTEGER,
    effect_size  DOUBLE,                       -- mean delta or correlation
    effect_unit  VARCHAR,                      -- 'ms', '%', 'σ', 'pts', etc.
    p_value      DOUBLE,                       -- null when test doesn't yield one
    verdict      VARCHAR NOT NULL,           -- 'confirmed' | 'refuted' | 'insufficient' | 'inconclusive' | 'error' (runner raised; not a result)
    summary      VARCHAR NOT NULL,           -- one-sentence narrative
    evidence     VARCHAR                       -- JSON dump of the per-day rows used
);

CREATE INDEX IF NOT EXISTS idx_lab_findings_question_run
    ON lab_findings (question_id, run_at DESC);

-- Seed catalogue: 6 starter hypotheses
INSERT INTO lab_questions (id, title, hypothesis, exposure, outcome, test_type, window_days, min_n, threshold, direction, vault_ref)
VALUES
    ('sleep_short_hrv_drop',
     'Short sleep depresses next-day HRV',
     'On nights you sleep <6.5h, next-morning HRV is at least 5ms below your trailing 28-day mean.',
     'sleep_hours < 6.5',
     'hrv_next_morning',
     'paired_t', 90, 10, 5.0, 'negative',
     'Walker 2017 — Why We Sleep, ch.7'),
    ('long_sleep_hrv_lift',
     'Long sleep lifts next-day HRV',
     'On nights you sleep ≥8h, next-morning HRV exceeds your trailing 28-day mean by ≥0.5σ.',
     'sleep_hours >= 8.0',
     'hrv_next_morning',
     'paired_t', 90, 8, 5.0, 'positive',
     'Watson AASM consensus 2015'),
    ('pickleball_next_morning_hrv',
     'Pickleball day depresses next-morning HRV',
     'Days following a pickleball session show lower next-morning HRV than no-session days.',
     'pickleball_session',
     'hrv_next_morning',
     'paired_t', 90, 12, 4.0, 'negative',
     'Bourdillon 2017 — exercise-HRV recovery'),
    ('skin_temp_illness_alarm',
     'Skin temp +1°F vs baseline precedes red recovery within 48h',
     'When skin temp rises ≥1°F above 28-day baseline, recovery score drops below 34 within the next 48h.',
     'skin_temp_delta_f >= 1.0',
     'red_recovery_within_48h',
     'change_point', 90, 6, 0.5, 'positive',
     'WHOOP 2022 — illness early-warning paper'),
    ('strain_high_rhr_next',
     'High strain day elevates RHR the next morning',
     'Days with strain >12 produce a +3bpm or higher RHR vs your trailing 28-day RHR baseline the next morning.',
     'strain > 12',
     'rhr_delta_next_morning',
     'paired_t', 90, 10, 3.0, 'positive',
     'Plews & Laursen 2014 — HRV-guided training'),
    ('push_pull_imbalance_recovery',
     'Push:pull imbalance correlates with poor recovery',
     'Within rolling 7-day windows where push:pull set-volume ratio sits outside 0.8–1.2, weekly avg recovery is meaningfully lower.',
     'push_pull_ratio outside 0.8-1.2',
     'recovery_avg_7d',
     'correlation', 180, 20, 0.30, 'either',
     'Israetel 2020 — Scientific Principles of Hypertrophy Training')
ON CONFLICT (id) DO NOTHING;

INSERT INTO schema_version (version) VALUES (19) ON CONFLICT DO NOTHING;
