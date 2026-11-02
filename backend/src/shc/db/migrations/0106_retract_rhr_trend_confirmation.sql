-- The rising-RHR finding was compared to a fixed threshold, not to other days.
-- Re-tested 2026-11-01 against non-trigger days: same hit rate, so no effect.
UPDATE lab_findings
SET verdict = 'inconclusive',
    summary = 'Below-baseline HRV followed rising RHR no more often than it followed other days (re-tested 2026-11-01).'
WHERE question_id = 'rhr_trend_hrv_drop' AND verdict = 'confirmed';
