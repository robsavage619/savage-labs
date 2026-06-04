-- Migration 0044: make the HRV baseline a true CALENDAR window (panel review M7).
--
-- 0034 used `ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING` over non-null-HRV rows.
-- With missed nights, "28 rows" silently spans 35–50+ calendar days, so hrv_sigma
-- — which trips the low-intensity gate at < -1.5σ — was measured against a
-- possibly weeks-stale baseline, inconsistent with the calendar-windowed RHR
-- baseline. Switch to a RANGE window over actual dates (prior 28 days, excluding
-- today), and expose the count so the metrics layer can require a minimum N.

CREATE OR REPLACE VIEW v_hrv_baseline_28d AS
SELECT
    date,
    hrv,
    AVG(hrv)    OVER w AS hrv_28d_avg,
    STDDEV(hrv) OVER w AS hrv_28d_sd,
    COUNT(hrv)  OVER w AS hrv_28d_n
FROM recovery
WHERE hrv IS NOT NULL
WINDOW w AS (
    ORDER BY date
    RANGE BETWEEN INTERVAL 28 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING
)
ORDER BY date;
