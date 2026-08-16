-- 0097: per-endpoint sync cursors for WHOOP, so a normal sync resumes from
-- the last-seen occurrence time instead of re-walking the whole account.
--
-- DECISIONS.md 2026-08-12 flagged this open: sync_cycle pages through 800+
-- cycles on every sync and 429s near the end, adding unnecessary load onto
-- the same WHOOP infrastructure whose 502s cause the token-desync reauth bug.
--
-- Reusing oauth_state(source=...) for these cursors was considered and
-- rejected: oauth_state is enumerated directly as the "connected data
-- sources" list in /api/oauth/status and DailyState.data_sources
-- (dashboard.py, subject.py) — one row per real external connection. Adding
-- whoop_recovery / whoop_sleep / whoop_workout / whoop_cycle rows there would
-- show up as four fake extra WHOOP connections in that UI. A dedicated table
-- keeps per-endpoint bookkeeping out of that surface entirely.

CREATE TABLE IF NOT EXISTS whoop_sync_cursor (
    endpoint    VARCHAR PRIMARY KEY,
    cursor      TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
