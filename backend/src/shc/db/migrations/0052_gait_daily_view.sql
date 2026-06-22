-- #29 — Make the Apple gait suite consumable downstream.
--
-- The gait metrics (walking_asymmetry_pct, walking_double_support_pct,
-- walking_speed_m_s, walking_step_length_m, stair_ascent_speed_m_s,
-- stair_descent_speed_m_s, walking_heart_rate_avg) already land in the
-- measurements table with clean metric keys — both the XML importer
-- (ingest/apple_xml.py) and the Shortcut webhook (api/routers/apple.py) INSERT
-- them there. The only gap was consumption: nothing read them back.
--
-- v_gait_daily pivots the daily-averaged gait metrics into one row per day so a
-- decision path can read walking_asymmetry_pct directly (e.g. to back the
-- forefoot-overload note). walking_asymmetry_28d is a trailing 28-day mean so a
-- single noisy day doesn't trigger the note.

CREATE OR REPLACE VIEW v_gait_daily AS
WITH daily AS (
    SELECT
        ts::DATE AS date,
        metric,
        AVG(value_num) AS value_avg
    FROM measurements
    WHERE source = 'apple_health'
      AND metric IN (
          'walking_asymmetry_pct',
          'walking_double_support_pct',
          'walking_speed_m_s',
          'walking_step_length_m',
          'stair_ascent_speed_m_s',
          'stair_descent_speed_m_s',
          'walking_heart_rate_avg'
      )
    GROUP BY ts::DATE, metric
),
pivoted AS (
    SELECT
        date,
        MAX(value_avg) FILTER (WHERE metric = 'walking_asymmetry_pct')      AS walking_asymmetry_pct,
        MAX(value_avg) FILTER (WHERE metric = 'walking_double_support_pct') AS walking_double_support_pct,
        MAX(value_avg) FILTER (WHERE metric = 'walking_speed_m_s')          AS walking_speed_m_s,
        MAX(value_avg) FILTER (WHERE metric = 'walking_step_length_m')      AS walking_step_length_m,
        MAX(value_avg) FILTER (WHERE metric = 'stair_ascent_speed_m_s')     AS stair_ascent_speed_m_s,
        MAX(value_avg) FILTER (WHERE metric = 'stair_descent_speed_m_s')    AS stair_descent_speed_m_s,
        MAX(value_avg) FILTER (WHERE metric = 'walking_heart_rate_avg')     AS walking_heart_rate_avg
    FROM daily
    GROUP BY date
)
SELECT
    date,
    walking_asymmetry_pct,
    walking_double_support_pct,
    walking_speed_m_s,
    walking_step_length_m,
    stair_ascent_speed_m_s,
    stair_descent_speed_m_s,
    walking_heart_rate_avg,
    AVG(walking_asymmetry_pct) OVER (
        ORDER BY date ROWS BETWEEN 27 PRECEDING AND CURRENT ROW
    ) AS walking_asymmetry_28d
FROM pivoted
ORDER BY date;
