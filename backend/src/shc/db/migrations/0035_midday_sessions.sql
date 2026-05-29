-- Midday session recommendations: Nike lunch-hour workout or recovery prescriptions.
-- One row per calendar day. session_type: 'workout' | 'recovery' | 'mixed'.
CREATE TABLE IF NOT EXISTS midday_sessions (
    session_date    DATE         PRIMARY KEY,
    session_type    VARCHAR(20)  NOT NULL,
    recommendation  JSON         NOT NULL,
    source          VARCHAR(50)  NOT NULL DEFAULT 'claude',
    generated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
