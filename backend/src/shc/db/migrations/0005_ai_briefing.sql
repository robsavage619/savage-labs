CREATE TABLE IF NOT EXISTS ai_briefing (
    briefing_date  DATE PRIMARY KEY,
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    model          VARCHAR NOT NULL,
    training_call  VARCHAR NOT NULL,       -- Push | Train | Maintain | Easy | Rest
    training_rationale TEXT NOT NULL,
    readiness_headline TEXT NOT NULL,
    coaching_note  TEXT NOT NULL,
    flags          TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    priority_metric VARCHAR,               -- hrv | sleep | recovery | load
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cache_read_tokens INTEGER,
    cost_usd       DOUBLE
);
