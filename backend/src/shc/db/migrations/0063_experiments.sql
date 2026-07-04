-- n-of-1 self-experiment framework: pre-registered single-subject studies.
--
-- The existing lab.py catalogue is OBSERVATIONAL — it mines associations from
-- passively-generated data. This adds the EXPERIMENTAL layer: Rob deliberately
-- manipulates one variable under a controlled design, so a confirmed result is
-- causal, not correlational. Pre-registration (hypothesis + design + analysis
-- plan locked before data is seen) and per-day arm assignment fixed up front are
-- the anti-p-hacking guarantees. A CONFIRMED result emits a governed personal
-- prior the engine can act on — the same treatment as personal_acwr_bands.

CREATE TABLE IF NOT EXISTS experiments (
    id                VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    slug              VARCHAR NOT NULL UNIQUE,          -- stable human key
    hypothesis        VARCHAR NOT NULL,
    manipulated       VARCHAR NOT NULL,                 -- variable, e.g. 'pre_lift_caffeine'
    condition_a       VARCHAR NOT NULL,                 -- control label, e.g. 'none'
    condition_b       VARCHAR NOT NULL,                 -- intervention label, e.g. '200mg'
    outcome_metric    VARCHAR NOT NULL,                 -- e.g. 'top_set_e1rm:Bench Press (Barbell)'
    outcome_direction VARCHAR NOT NULL DEFAULT 'higher_better',  -- higher_better | lower_better
    design            VARCHAR NOT NULL DEFAULT 'randomized_alternating',
    min_per_arm       INTEGER NOT NULL DEFAULT 6,       -- N-gate per arm
    min_effect        DOUBLE  NOT NULL DEFAULT 0.0,     -- smallest meaningful effect (outcome units)
    washout_hours     INTEGER NOT NULL DEFAULT 0,
    started_on        DATE    NOT NULL DEFAULT CURRENT_DATE,
    planned_end       DATE,
    status            VARCHAR NOT NULL DEFAULT 'active',  -- active | complete | abandoned
    preregistered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes             VARCHAR
);

-- Per-day arm assignment + adherence + measured outcome. assigned_arm is a
-- deterministic function of (slug, day) so it is reproducible and fixed BEFORE
-- the outcome is known — it cannot be reverse-engineered after seeing results.
CREATE TABLE IF NOT EXISTS experiment_log (
    experiment_id  VARCHAR NOT NULL,
    day            DATE    NOT NULL,
    assigned_arm   VARCHAR NOT NULL,                    -- 'A' | 'B'
    adhered        BOOLEAN,                             -- did Rob comply (NULL = unknown)
    outcome_value  DOUBLE,                              -- filled from the data stream on scoring
    note           VARCHAR,
    PRIMARY KEY (experiment_id, day)
);

-- Scored result of an experiment. verdict vocabulary matches the lab catalogue.
CREATE TABLE IF NOT EXISTS experiment_result (
    experiment_id   VARCHAR PRIMARY KEY,
    verdict         VARCHAR NOT NULL,                   -- CONFIRMED|REFUTED|INCONCLUSIVE|INSUFFICIENT_N
    n_a             INTEGER NOT NULL,
    n_b             INTEGER NOT NULL,
    mean_a          DOUBLE,
    mean_b          DOUBLE,
    effect          DOUBLE,                             -- mean_b - mean_a (outcome units)
    effect_ci_low   DOUBLE,
    effect_ci_high  DOUBLE,
    p_value         DOUBLE,
    summary         VARCHAR,
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Governed personal prior emitted by a CONFIRMED experiment. Read by the engine;
-- actuation is gated + auditable, same discipline as the fitted ACWR/volume bands.
CREATE TABLE IF NOT EXISTS experiment_prior (
    experiment_id   VARCHAR PRIMARY KEY,
    prior_key       VARCHAR NOT NULL,                   -- e.g. 'pre_lift_caffeine.top_set_e1rm_pct'
    effect          DOUBLE  NOT NULL,
    effect_ci_low   DOUBLE,
    effect_ci_high  DOUBLE,
    outcome_metric  VARCHAR NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
