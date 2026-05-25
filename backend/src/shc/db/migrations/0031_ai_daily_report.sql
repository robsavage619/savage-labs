-- Unified daily AI report — one artifact per day covering all areas (readiness,
-- training call, workout, health story, body composition), replacing the need to
-- run five separate copy-prompt loops. Generated via copy-prompt → CC → POST-back.

CREATE TABLE IF NOT EXISTS ai_daily_report (
    report_date        DATE PRIMARY KEY,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    model              VARCHAR NOT NULL DEFAULT 'claude',
    training_call      VARCHAR,            -- Push | Train | Maintain | Easy | Rest
    readiness_headline TEXT,
    sections           TEXT NOT NULL DEFAULT '[]'  -- JSON: [{title, body_md}, ...]
);

INSERT INTO schema_version (version) VALUES (31) ON CONFLICT DO NOTHING;
