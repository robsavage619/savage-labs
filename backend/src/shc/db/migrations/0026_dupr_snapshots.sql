-- dupr_snapshots: daily snapshot of the current DUPR rating, pulled from the
-- unofficial DUPR API (see ingest/dupr.py). One row per calendar date; the
-- series gives the rating trajectory the goal scorecard reads. tournament_events
-- (migration 0025) remains the home for per-event before/after results.
CREATE TABLE IF NOT EXISTS dupr_snapshots (
    date DATE PRIMARY KEY,
    doubles DOUBLE,
    singles DOUBLE,
    doubles_provisional BOOLEAN,
    singles_provisional BOOLEAN,
    raw JSON,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
