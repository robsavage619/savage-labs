-- Hevy exercise template cache (populated on first sync)
CREATE TABLE IF NOT EXISTS hevy_exercise_templates (
    id                       VARCHAR PRIMARY KEY,
    title                    VARCHAR NOT NULL,
    primary_muscle_group     VARCHAR,
    secondary_muscle_groups  VARCHAR,  -- JSON array as text
    category                 VARCHAR,
    synced_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tracks routines pushed to Hevy so we can upsert rather than duplicate
CREATE TABLE IF NOT EXISTS hevy_routines (
    date        DATE PRIMARY KEY,
    routine_id  VARCHAR NOT NULL,
    title       VARCHAR NOT NULL,
    pushed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_version (version) VALUES (2) ON CONFLICT DO NOTHING;
