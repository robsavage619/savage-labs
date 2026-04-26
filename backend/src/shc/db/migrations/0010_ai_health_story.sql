CREATE TABLE IF NOT EXISTS ai_health_story (
    story_date    DATE PRIMARY KEY,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    model         VARCHAR,
    narrative     TEXT NOT NULL,
    sources       TEXT NOT NULL DEFAULT '[]'  -- JSON array of vault note names cited
);
