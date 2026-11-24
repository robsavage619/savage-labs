-- Registry of long-horizon health markers: definitions only, no personal value.
-- Latest values are read at evaluation time from source_table/source_metric.
-- target_source is a vault note filename, 'set by clinician', or NULL (no target set).
-- shc.health_markers.seed() re-validates the citations; a test keeps this list identical to it.
CREATE TABLE IF NOT EXISTS health_markers (
    marker        VARCHAR PRIMARY KEY,
    label         VARCHAR NOT NULL,
    domain        VARCHAR NOT NULL,
    source_table  VARCHAR NOT NULL,
    source_metric VARCHAR NOT NULL,
    unit          VARCHAR NOT NULL,
    target_low    DOUBLE,
    target_high   DOUBLE,
    target_source VARCHAR,
    retest_days   INTEGER NOT NULL,
    direction     VARCHAR NOT NULL CHECK (direction IN ('higher_better', 'lower_better', 'in_range'))
);

INSERT INTO health_markers (marker, label, domain, source_table, source_metric, unit,
    target_low, target_high, target_source, retest_days, direction) VALUES
    ('vo2max', 'Aerobic fitness (VO2max)', 'cardiorespiratory', 'measurements', 'vo2_max_whoop', 'mL/kg/min', NULL, NULL, NULL, 90, 'higher_better'),
    ('resting_hr', 'Resting heart rate', 'cardiovascular', 'recovery', 'rhr', 'bpm', NULL, NULL, NULL, 14, 'lower_better'),
    ('hrv', 'Heart rate variability', 'cardiovascular', 'recovery', 'hrv', 'ms', NULL, NULL, NULL, 14, 'higher_better'),
    ('bp_systolic', 'Blood pressure (top number)', 'cardiovascular', 'measurements', 'blood_pressure_systolic', 'mmHg', NULL, NULL, NULL, 90, 'lower_better'),
    ('bp_diastolic', 'Blood pressure (bottom number)', 'cardiovascular', 'measurements', 'blood_pressure_diastolic', 'mmHg', NULL, NULL, NULL, 90, 'lower_better'),
    ('apob', 'ApoB (artery-clogging particle count)', 'lipids', 'labs', 'ApoB|Apolipoprotein B', 'mg/dL', NULL, 60.0, 'apob.md', 180, 'lower_better'),
    ('ldl_c', 'LDL cholesterol', 'lipids', 'labs', 'LDL Cholesterol (calc)', 'mg/dL', NULL, NULL, NULL, 180, 'lower_better'),
    ('hba1c', 'HbA1c (3-month blood sugar)', 'metabolic', 'labs', 'HbA1c', '%', NULL, NULL, NULL, 180, 'lower_better'),
    ('alt', 'ALT (liver enzyme)', 'liver', 'labs', 'ALT', 'U/L', NULL, 30.0, 'attia-2023-ch6-crisis-of-abundance.md', 180, 'lower_better'),
    ('waist', 'Waist circumference', 'body', 'measurements', 'waist_circumference_cm', 'cm', NULL, NULL, NULL, 30, 'lower_better'),
    ('grip', 'Grip strength', 'strength', 'measurements', 'grip_strength_kg', 'kg', NULL, NULL, NULL, 90, 'higher_better'),
    ('sleep_duration', 'Sleep duration', 'sleep', 'sleep', 'duration_h', 'h', NULL, NULL, NULL, 14, 'in_range'),
    ('sleep_consistency', 'Sleep consistency', 'sleep', 'sleep', 'sleep_consistency_pct', '%', NULL, NULL, NULL, 14, 'higher_better'),
    ('steps', 'Daily steps', 'activity', 'measurements', 'step_count', 'steps', NULL, NULL, NULL, 14, 'higher_better')
ON CONFLICT (marker) DO NOTHING;
