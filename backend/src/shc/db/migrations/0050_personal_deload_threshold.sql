-- Migration 0050: personal deload-trigger threshold.
--
-- Closes the last open self-learning loop. DELOAD_MUSCLE_THRESHOLD (number of
-- muscles that must regress before a fatigue deload fires) was a fixed RP
-- population default (3). This table persists a threshold fitted from Rob's own
-- signal-driven deload history: the typical regressing-muscle count in the week
-- before each non-calendar deload. deload_check() reads it, falling back to the
-- population default when too few signal deloads exist to fit.

CREATE TABLE IF NOT EXISTS personal_deload_threshold (
    id                INTEGER PRIMARY KEY DEFAULT 1,   -- single-row table
    threshold         INTEGER NOT NULL,                -- fitted muscle-count trigger
    n_events          INTEGER NOT NULL,                -- signal deloads the fit is based on
    precursor_median  DOUBLE,                          -- median regressing-muscle precursor count
    fitted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
