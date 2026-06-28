-- Migration 0056: persistent muscle emphasis (Rob's bring-up priorities).
--
-- Emphasis was a hardcoded frozenset (EMPHASIS_MUSCLES = {biceps, glutes, traps})
-- in autoregulation.py — nothing Rob said in chat could reach the engine, which
-- reads only the DB. This table is the lever: load_emphasis() reads it and
-- _resolve_emphasis() folds in the physique signal, falling back to the frozenset
-- prior when the table is empty. Seeded with the existing prior so day-one
-- behavior is unchanged; POST /training/emphasis is the write path.

CREATE TABLE IF NOT EXISTS muscle_emphasis (
    muscle      TEXT PRIMARY KEY,
    weight      DOUBLE NOT NULL DEFAULT 1.0,   -- emphasis strength (reserved for future ramp scaling)
    note        TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO muscle_emphasis (muscle, note) VALUES
    ('biceps', 'initial prior — lagging bring-up'),
    ('glutes', 'initial prior — lagging bring-up'),
    ('traps',  'initial prior — lagging bring-up')
ON CONFLICT DO NOTHING;
