-- Retire the rarely-actionable yoga study (Rob does yoga ~twice a year, so it
-- never accumulates enough exposure days) and activate a strength-volume →
-- next-day HRV study in its place. Runner: _run_lift_volume_hrv_drop.

UPDATE lab_questions SET enabled = FALSE, retired_at = now() WHERE id = 'yoga_hrv_lift';

INSERT INTO lab_questions
    (id, title, hypothesis, exposure, outcome, test_type,
     window_days, min_n, threshold, direction, vault_ref, enabled, queued_order)
VALUES
    ('lift_volume_hrv_drop',
     'Heavy lift volume depresses next-day HRV',
     'Days with higher strength-training tonnage are followed by lower next-morning HRV relative to your trailing 28-day mean.',
     'strength_tonnage_prev_day',
     'hrv_next_morning_deviation',
     'correlation', 365, 10, 0.2, 'negative',
     'Plews 2013 — HRV-guided training-load monitoring',
     TRUE, NULL)
ON CONFLICT (id) DO UPDATE SET enabled = TRUE, retired_at = NULL, queued_order = NULL;

INSERT INTO schema_version (version) VALUES (28) ON CONFLICT DO NOTHING;
