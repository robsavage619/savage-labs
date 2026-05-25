-- Exclude today's value from its own HRV baseline.
--
-- The 28-day baseline used `ROWS BETWEEN 27 PRECEDING AND CURRENT ROW`, so the
-- current day was part of the mean and SD it is then measured against. That
-- biases the deviation (hrv_sigma) toward 0 — today literally helped set the
-- baseline it's compared to — and inflates SD on spike days, shrinking sigma
-- further. Since hrv_sigma < -1.5 trips the low-intensity gate, this dampened a
-- real red-HRV signal. Use the prior 28 rows only (28 PRECEDING .. 1 PRECEDING).

CREATE OR REPLACE VIEW v_hrv_baseline_28d AS
SELECT
    date,
    hrv,
    AVG(hrv) OVER (ORDER BY date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS hrv_28d_avg,
    STDDEV(hrv) OVER (ORDER BY date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS hrv_28d_sd
FROM recovery
WHERE hrv IS NOT NULL
ORDER BY date;

INSERT INTO schema_version (version) VALUES (34) ON CONFLICT DO NOTHING;
