-- Migration 0047: Phase 3 self-learning schema additions.
--
-- 1. weekly_tonnage_kg column on exercise_weekly_e1rm — enables the rep-progression
--    / volume-load blend in score_exercise (flat e1RM + rising tonnage = hypertrophy
--    progress, not a stall).
-- 2. personal_acwr_bands table — persists fitted resistance/conditioning ACWR
--    thresholds derived from Rob's own load distribution, replacing the heuristic
--    population priors in metrics.py.

ALTER TABLE exercise_weekly_e1rm
    ADD COLUMN IF NOT EXISTS weekly_tonnage_kg DOUBLE;

CREATE TABLE IF NOT EXISTS personal_acwr_bands (
    arm             VARCHAR NOT NULL,   -- 'resistance' | 'conditioning'
    threshold_name  VARCHAR NOT NULL,   -- 'rest' | 'low' | 'mod' | 'forbid_legs'
    value           DOUBLE NOT NULL,
    sample_weeks    INTEGER NOT NULL,
    fitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arm, threshold_name)
);
