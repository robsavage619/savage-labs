-- Migration 0051: engine accuracy history.
--
-- prescription_accuracy() backtests the controller's calls on demand, but the
-- result was never stored — so there was no way to see whether the engine is
-- getting better or worse over time (the core risk of a single-user fit). This
-- table snapshots overall accuracy once per ISO week from compute_all_scores,
-- giving a drift signal the dashboard can chart.

CREATE TABLE IF NOT EXISTS engine_accuracy_history (
    week_start   DATE PRIMARY KEY,   -- ISO Monday of the snapshot week
    overall      DOUBLE,             -- blended logged+retroactive accuracy [0,1], NULL if unscored
    n_scored     INTEGER NOT NULL,   -- prediction pairs the accuracy is based on
    snapshot_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
