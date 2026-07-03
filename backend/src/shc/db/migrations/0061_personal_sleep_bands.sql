-- Migration 0061: Personal sleep-architecture bands.
--
-- disturbance_count and sleep_cycle_count gates in metrics.py used fixed
-- population thresholds (>=12 disturbances, <4 cycles) with no personal
-- baseline, unlike every other autonomic gate (HRV sigma, RHR %, ACWR
-- percentiles). Rob has diagnosed, off-CPAP obstructive sleep apnea, which
-- structurally elevates disturbance counts and fragments cycle counts most
-- nights regardless of whether a given night is unusually bad for him. This
-- table stores fitted personal percentiles (80th for disturbance count, 20th
-- for cycle count) so the gate reacts to deviation from Rob's own nightly
-- baseline instead of a population norm his condition guarantees he'll clear.

CREATE TABLE IF NOT EXISTS personal_sleep_bands (
    metric          VARCHAR NOT NULL,   -- 'disturbance_count' | 'sleep_cycle_count'
    threshold_name  VARCHAR NOT NULL,   -- 'p80' | 'p20'
    value           DOUBLE NOT NULL,
    sample_nights   INTEGER NOT NULL,
    fitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (metric, threshold_name)
);
