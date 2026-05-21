-- dupr_matches: per-match history pulled from the unofficial DUPR API.
-- One row per matchId; synced via ingest/dupr.sync_matches().
-- Joins with recovery table on event_date for recovery-context display.
CREATE TABLE IF NOT EXISTS dupr_matches (
    match_id   BIGINT PRIMARY KEY,
    event_date DATE    NOT NULL,
    event_name VARCHAR,
    venue      VARCHAR,
    format     VARCHAR,          -- DOUBLES | SINGLES | MIXED
    partner_name  VARCHAR,
    opponent1_name VARCHAR,
    opponent2_name VARCHAR,
    won        BOOLEAN,
    -- scores per game (us / them); NULL = game not played
    game1_us   SMALLINT,  game1_them SMALLINT,
    game2_us   SMALLINT,  game2_them SMALLINT,
    game3_us   SMALLINT,  game3_them SMALLINT,
    dupr_pre   DOUBLE,
    dupr_post  DOUBLE,
    dupr_delta DOUBLE,
    raw        JSON,
    synced_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
