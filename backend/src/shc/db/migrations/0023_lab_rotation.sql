-- Lab hypothesis rotation: retirement tracking + queued bank of future hypotheses.
--
-- When a question accumulates 3 consecutive identical confirmed/refuted verdicts
-- with n >= 1.5 * min_n, the runner marks it retired and promotes the next
-- queued question (lowest queued_order) from the bank.

ALTER TABLE lab_questions ADD COLUMN IF NOT EXISTS retired_at  TIMESTAMPTZ;
ALTER TABLE lab_questions ADD COLUMN IF NOT EXISTS queued_order INTEGER;

-- Bank of queued hypotheses (enabled=FALSE, retired_at=NULL, queued_order set).
-- All have a registered _run_* function in lab.py — they're just waiting their turn.
INSERT INTO lab_questions
    (id, title, hypothesis, exposure, outcome, test_type,
     window_days, min_n, threshold, direction, vault_ref, enabled, queued_order)
VALUES
    ('yoga_hrv_lift',
     'Yoga sessions improve next-morning HRV',
     'Days following a yoga session show higher next-morning HRV than days following no yoga.',
     'yoga_session',
     'hrv_next_morning',
     'paired_t', 120, 12, 4.0, 'positive',
     'Dolezal 2017 — sleep-exercise review',
     FALSE, 1),

    ('consecutive_training_recovery_drop',
     'Back-to-back training days depress next-day recovery',
     'Days following two or more consecutive strength sessions show lower recovery scores than days after a rest day.',
     'consecutive_strength_days >= 2',
     'recovery_score_next_day',
     'paired_t', 180, 14, 5.0, 'negative',
     'Israetel 2020 — Ch3 Fatigue Management',
     FALSE, 2),

    ('two_pb_3d_hrv_drop',
     'Two pickleball sessions in 3 days compounds HRV depression',
     'Rolling 3-day windows with 2+ pickleball sessions show lower next-morning HRV than windows with exactly 1 session.',
     'pickleball_sessions_3d >= 2',
     'hrv_next_morning',
     'paired_t', 180, 12, 3.0, 'negative',
     'Bourdillon 2017 — exercise-HRV recovery',
     FALSE, 3),

    ('weekly_volume_spike_recovery',
     'Training volume spike correlates with lower recovery',
     'Weeks where total gym set count exceeds 1.5× the prior 4-week average show lower average weekly recovery score.',
     'weekly_sets > 1.5x_4wk_avg',
     'avg_recovery_that_week',
     'correlation', 180, 16, 0.25, 'negative',
     'Gabbett 2016 — ACWR training load',
     FALSE, 4),

    ('rest_day_hrv_rebound',
     'Full rest days produce higher next-morning HRV',
     'Days with no Hevy session and no cardio show higher next-morning HRV than active training days.',
     'no_hevy_no_cardio',
     'hrv_next_morning',
     'paired_t', 120, 14, 3.0, 'positive',
     'Plews & Laursen 2014 — HRV-guided training',
     FALSE, 5),

    ('energy_checkin_hrv_correlation',
     'Self-reported energy correlates with same-day HRV',
     'Daily energy check-in score (1–10) correlates positively with same-morning HRV.',
     'energy_1_10',
     'hrv_same_morning',
     'correlation', 120, 20, 0.25, 'positive',
     'Shaffer 2017 — HRV metrics and norms',
     FALSE, 6),

    ('rhr_trend_hrv_drop',
     '7-day rising RHR trend predicts HRV below baseline',
     'When 7-day average RHR rises ≥2 bpm above the prior 7-day average, HRV falls below 28-day mean within 3 days.',
     'rhr_7d_trend >= +2bpm',
     'hrv_below_28d_mean_within_3d',
     'change_point', 180, 10, 0.4, 'positive',
     'Plews & Laursen 2014 — HRV-guided training',
     FALSE, 7),

    ('sleep_quality_checkin_hrv',
     'Low self-reported sleep quality correlates with reduced HRV',
     'Nights where sleep quality check-in is ≤5/10 are followed by next-morning HRV below the 28-day mean.',
     'sleep_quality_1_10 <= 5',
     'hrv_next_morning',
     'paired_t', 120, 14, 4.0, 'negative',
     'Walker 2017 — Why We Sleep, ch.7',
     FALSE, 8)

ON CONFLICT (id) DO NOTHING;

INSERT INTO schema_version (version) VALUES (23) ON CONFLICT DO NOTHING;
