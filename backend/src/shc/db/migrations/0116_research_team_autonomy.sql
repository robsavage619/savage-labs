-- The research team's own state. Each specialist keeps one agenda row it
-- replaces whole (the notebook records what changed). Custom measurements are
-- one guarded read-only SELECT each, proposed by a specialist and usable in a
-- formal question only after the methodologist approves it.
CREATE TABLE IF NOT EXISTS research_agenda (
    researcher  VARCHAR PRIMARY KEY,
    interests   VARCHAR NOT NULL DEFAULT '',
    open_leads  VARCHAR NOT NULL DEFAULT '[]',   -- JSON list of {lead, why, priority, status, opened}
    hunches     VARCHAR NOT NULL DEFAULT '',
    next_steps  VARCHAR NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_custom_features (
    name           VARCHAR PRIMARY KEY,           -- custom:<slug>
    owner          VARCHAR NOT NULL,
    description    VARCHAR NOT NULL,
    unit           VARCHAR NOT NULL,
    timing         VARCHAR NOT NULL,              -- morning | day
    sql            VARCHAR NOT NULL,
    status         VARCHAR NOT NULL DEFAULT 'proposed',  -- proposed | approved | rejected
    review_reason  VARCHAR,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
