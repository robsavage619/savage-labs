-- Signals the public OAuth API does not expose at all, pulled from the private
-- iOS surface (see ingest/whoop_private.py for the ToS caveat).
--
-- Deliberately NOT stored here: sleep stage totals and recovery/strain
-- contributors. The public API already supplies those and DailyState is the
-- single source of truth for them — a second copy would be a second answer.

-- One row per day for the daily scalars, so the join into DailyState is a
-- single lookup rather than four.
CREATE TABLE IF NOT EXISTS whoop_private_daily (
    date                      DATE PRIMARY KEY,
    -- Sleep need (ms on the wire, stored as minutes to match the sleep table)
    need_total_min            DOUBLE,
    need_baseline_min         DOUBLE,
    need_strain_min           DOUBLE,
    need_debt_min             DOUBLE,
    need_nap_min              DOUBLE,
    -- WHOOP's own recommended sleep window — the target Rob's midpoint
    -- variability should be measured against.
    optimal_bedtime_start     VARCHAR,
    optimal_bedtime_end       VARCHAR,
    recommended_tib_min       DOUBLE,   -- for the 100% sleep-performance tier
    -- Stress monitor (no public-API equivalent)
    stress_score              DOUBLE,   -- 0.0–3.0 scale
    stress_level              VARCHAR,  -- LOW / MEDIUM / HIGH
    stress_state              VARCHAR,  -- e.g. BALANCED
    stress_high_pct           DOUBLE,   -- fraction of sampled day at HIGH
    sleeping_hr_baseline      DOUBLE,   -- distinct from waking RHR
    content_hash              VARCHAR NOT NULL
);

-- Per-sample stress curve. Kept separate from the daily row because it is
-- ~450 points/day and nothing in the engine reads it per-point yet.
CREATE TABLE IF NOT EXISTS whoop_stress_timeline (
    date          DATE NOT NULL,
    sampled_at    TIMESTAMPTZ NOT NULL,
    value         DOUBLE,
    level         VARCHAR,
    PRIMARY KEY (date, sampled_at)
);

-- WHOOP's own server-side impact analysis. Snapshotted with an as_of date
-- because it is a rolling recomputation over full history, not a daily fact.
CREATE TABLE IF NOT EXISTS whoop_behavior_impact (
    as_of            DATE NOT NULL,
    impact_uuid      VARCHAR NOT NULL,
    title            VARCHAR NOT NULL,
    impact_pct       DOUBLE,
    impact_style     VARCHAR,   -- POSITIVE / NEGATIVE / NEGLIGIBLE_* / INSUFFICIENT
    tag_style        VARCHAR,   -- AUTOMATED for metric-derived, else journal-derived
    yes_count        INTEGER,
    no_count         INTEGER,
    PRIMARY KEY (as_of, impact_uuid)
);

-- Zone boundaries WHOOP actually used to compute the zone minutes already in
-- cardio_sessions. Without these the z0–z5 columns are uninterpretable: the
-- cutoffs are NOT the documented 50/60/70/80/90% of max (Z5 starts at 93%).
CREATE TABLE IF NOT EXISTS whoop_hr_zones (
    zone_id            VARCHAR PRIMARY KEY,
    min_bpm            INTEGER,
    max_bpm            INTEGER,
    max_hr             INTEGER,
    effective_at       TIMESTAMPTZ,
    fetched_at         TIMESTAMPTZ NOT NULL
);

INSERT INTO schema_version (version) VALUES (94) ON CONFLICT DO NOTHING;
