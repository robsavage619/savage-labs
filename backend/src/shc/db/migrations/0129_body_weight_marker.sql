-- Body weight joins the health markers, read from the lab's approved weigh-in measurement
-- (custom:weighin_lb). No target: it is tracked as a trend, with a 90% range, not judged.
INSERT INTO health_markers (marker, label, domain, source_table, source_metric, unit,
    target_low, target_high, target_source, retest_days, direction) VALUES
    ('body_weight', 'Body weight', 'body', 'custom', 'weighin_lb', 'lb', NULL, NULL, NULL, 7, 'lower_better')
ON CONFLICT (marker) DO NOTHING;
