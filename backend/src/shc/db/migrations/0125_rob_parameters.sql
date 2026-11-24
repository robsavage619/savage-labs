-- The Rob Model registry: one row per thing the lab knows about one person.
-- Each parameter starts from a published prior (prior_source is a vault note
-- filename) and carries the value the engine currently fits from his own data.
-- Rows are written only by shc.rob_model.refresh, which reads engine-owned
-- tables; nothing personal is seeded here.

CREATE TABLE IF NOT EXISTS rob_parameters (
    key            VARCHAR PRIMARY KEY,
    domain         VARCHAR NOT NULL,       -- training | recovery | sleep | health
    label          VARCHAR NOT NULL,       -- plain words
    unit           VARCHAR,
    prior_mean     DOUBLE,
    prior_sd       DOUBLE,
    prior_source   VARCHAR NOT NULL,       -- vault note filename, or 'no published prior'
    post_mean      DOUBLE,
    post_sd        DOUBLE,
    evidence_kind  VARCHAR NOT NULL,       -- experiment | fitted | observed
    n_evidence     INTEGER NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumer       VARCHAR,                -- engine setting that reads it, or NULL
    status         VARCHAR NOT NULL        -- prior only | learning | established
);
