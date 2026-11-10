-- The research team's shared state. Hypotheses are data (a JSON spec frozen by
-- hash at registration), results are appended per run, beliefs carry a prior
-- with its citation and a posterior rebuilt from linked results, and the
-- notebook is append-only: the API offers no update or delete for it.
CREATE TABLE IF NOT EXISTS research_beliefs (
    id            VARCHAR PRIMARY KEY,
    claim         VARCHAR NOT NULL,
    outcome       VARCHAR NOT NULL,
    prior_mean    DOUBLE  NOT NULL,
    prior_sd      DOUBLE  NOT NULL,
    prior_source  VARCHAR NOT NULL,
    post_mean     DOUBLE  NOT NULL,
    post_sd       DOUBLE  NOT NULL,
    n_results     INTEGER NOT NULL DEFAULT 0,
    decision      VARCHAR,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_hypotheses (
    id          VARCHAR PRIMARY KEY,
    slug        VARCHAR NOT NULL UNIQUE,
    question    VARCHAR NOT NULL,
    spec        VARCHAR NOT NULL,
    spec_hash   VARCHAR NOT NULL,
    belief_id   VARCHAR,
    author      VARCHAR NOT NULL,
    status      VARCHAR NOT NULL,          -- registered | underpowered | retired
    power       VARCHAR,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_results (
    id             VARCHAR PRIMARY KEY,
    hypothesis_id  VARCHAR NOT NULL,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_a            INTEGER,
    n_b            INTEGER,
    effect         DOUBLE,
    se             DOUBLE,
    ci_low         DOUBLE,
    ci_high        DOUBLE,
    p              DOUBLE,
    design_effect  DOUBLE,
    verdict        VARCHAR NOT NULL,
    summary        VARCHAR,
    power          VARCHAR
);

CREATE TABLE IF NOT EXISTS research_notebook (
    id      VARCHAR PRIMARY KEY,
    written_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    author  VARCHAR NOT NULL,
    kind    VARCHAR NOT NULL,                -- proposal | review | result | belief | note | error
    ref     VARCHAR,
    title   VARCHAR NOT NULL,
    body    VARCHAR,
    data    VARCHAR
);
