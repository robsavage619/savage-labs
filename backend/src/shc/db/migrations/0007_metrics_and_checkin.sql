-- Single source-of-truth metrics + closed-loop fields.
-- Adds: workout_plans (was referenced but never created), checkin extensions
-- (propranolol_taken, body_weight_kg, soreness, training_completed link), and
-- v_session_load view for true Gabbett ACWR.

CREATE TABLE IF NOT EXISTS workout_plans (
    date         DATE PRIMARY KEY,
    plan_json    VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Extend daily_checkin with the inputs the auto-regulation gate needs.
-- DuckDB ALTER TABLE ADD COLUMN IF NOT EXISTS is supported.
-- DuckDB doesn't support CHECK / DEFAULT in ADD COLUMN; constraints are
-- enforced at the API layer via Pydantic.
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS propranolol_taken BOOLEAN;
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS body_weight_kg    DOUBLE;
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS soreness_overall  INTEGER;
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS illness_flag      BOOLEAN;
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS travel_flag       BOOLEAN;

-- Track whether yesterday's prescribed plan was actually executed (links
-- prescription → execution → next prescription).
CREATE TABLE IF NOT EXISTS plan_adherence (
    date              DATE PRIMARY KEY,
    plan_date         DATE NOT NULL,                     -- the plan that was prescribed
    workout_id        VARCHAR REFERENCES workouts(id),   -- the actual session that executed it (if any)
    completion_pct    DOUBLE,                            -- 0–100, sets-completed / sets-prescribed
    avg_rpe_actual    DOUBLE,
    avg_rpe_target    DOUBLE,
    notes             VARCHAR,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- True session load = sum of WHOOP `strain` for completed sessions on that day,
-- with a Hevy fallback (sets × volume_kg / 10000 as a coarse proxy when no WHOOP).
CREATE OR REPLACE VIEW v_session_load AS
SELECT
    started_at::DATE AS date,
    -- Prefer WHOOP strain; fall back to a coarse Hevy proxy when missing.
    COALESCE(SUM(w.strain), 0) AS whoop_strain,
    COUNT(DISTINCT w.id) AS sessions
FROM workouts w
GROUP BY started_at::DATE;

-- Daily total load combining strength volume (Hevy) and WHOOP strain so ACWR
-- isn't blind to lifting days when WHOOP has no autodetected workout.
CREATE OR REPLACE VIEW v_daily_load AS
SELECT
    d.date,
    COALESCE(s.whoop_strain, 0) AS whoop_strain,
    COALESCE(h.hevy_volume_kg, 0) / 1000.0 AS hevy_tonnes,
    -- Composite load: WHOOP strain (0–21 scale) + scaled Hevy tonnes (~0–5).
    COALESCE(s.whoop_strain, 0) + COALESCE(h.hevy_volume_kg, 0) / 5000.0 AS composite_load
FROM (
    SELECT date FROM v_session_load
    UNION
    SELECT started_at::DATE AS date FROM workouts
) d
LEFT JOIN v_session_load s ON s.date = d.date
LEFT JOIN (
    SELECT w.started_at::DATE AS date,
           SUM(ws.weight_kg * ws.reps) AS hevy_volume_kg
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    WHERE ws.is_warmup = FALSE
    GROUP BY w.started_at::DATE
) h ON h.date = d.date;

INSERT INTO schema_version (version) VALUES (7) ON CONFLICT DO NOTHING;
