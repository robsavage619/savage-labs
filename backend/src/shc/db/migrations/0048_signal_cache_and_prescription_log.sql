-- Migration 0048: materialized signal quality cache + prescription feedback loop.

-- Avoids recomputing signal quality on every /training/prescription request.
CREATE TABLE IF NOT EXISTS muscle_signal_cache (
    muscle           VARCHAR PRIMARY KEY,
    scored_weeks     INTEGER NOT NULL,
    signal_stability DOUBLE  NOT NULL,
    confidence       DOUBLE  NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Forward-looking prescription log: records each week's per-muscle call,
-- then scores it 3 weeks later by checking actual perf outcomes.
CREATE TABLE IF NOT EXISTS muscle_prescription_log (
    week_start      DATE    NOT NULL,
    muscle          VARCHAR NOT NULL,
    action          VARCHAR NOT NULL,   -- 'add' | 'hold' | 'cut' | 'deload'
    target_sets     INTEGER NOT NULL,
    perf_at_time    INTEGER,            -- muscle-level perf when prescribed
    landmark_source VARCHAR NOT NULL DEFAULT 'population',
    confidence      DOUBLE  NOT NULL DEFAULT 0.0,
    outcome_perf    INTEGER,            -- muscle perf_score 3 weeks later
    outcome_week    DATE,
    correct         BOOLEAN,            -- did the direction match?
    scored_at       TIMESTAMPTZ,
    PRIMARY KEY (week_start, muscle)
);
