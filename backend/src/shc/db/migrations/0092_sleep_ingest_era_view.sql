-- 0092: label the two sleep-staging regimes so ad-hoc analysis stops comparing
-- two different rulers.
--
-- See DECISIONS.md 2026-08-10. Sleep-architecture columns shift discontinuously
-- between 2025-02 and 2025-03, at the boundary where the WHOOP CSV export ends
-- and API sync takes over. Measured on REM as a share of sleep, monthly means:
--
--   pre  (2024-01..2025-02, 14 months): 27.3% .. 34.7%, mean nightly SD 8.8
--   post (2025-03..,        18 months): 19.7% .. 25.5%, mean nightly SD 5.0
--
-- The two ranges do not overlap — the pre-period's worst month beats the
-- post-period's best. Nightly dispersion also nearly halves, which a
-- physiological change does not usually do but a smoother staging model does.
-- Corroborating: whoop_journal independently terminates at 2025-02-15, and
-- across the same boundary disturbances fell 13->9, awake minutes ~70->~26 and
-- efficiency rose 88%->94% — every fragmentation metric improved, which rules
-- out the obvious physiological story (untreated OSA) for the REM decline.
--
-- No live code path needs this view: every consumer reads a bounded window
-- (14d in metrics._sleep, 180d in the bands fitter, 365d at the widest
-- lab_questions), and the boundary recedes by a day per day, so no rolling
-- window can reach it. The exposure this closes is ad-hoc querying, which is
-- exactly what nearly produced the wrong conclusion on 2026-08-10.
--
-- The boundary is resolved to the MONTH, not the night. Nightly SD in the
-- pre-period is 8.8pp against a shift of ~6pp, so no single night separates the
-- regimes and none should be claimed to. 2025-03-01 is the first day of the
-- first post-regime month, not a measured changepoint.
--
-- How much of the shift is real physiology underneath the re-scoring is
-- unknown. The CPAP discontinuation date was never recorded, so its share is
-- untestable; if that date ever surfaces it becomes a separable question.

CREATE OR REPLACE VIEW v_sleep_era AS
SELECT
    s.*,
    CASE
        WHEN s.night_date < DATE '2025-03-01' THEN 'csv'
        ELSE 'api'
    END AS ingest_era
FROM sleep s;
