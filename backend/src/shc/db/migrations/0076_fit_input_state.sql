-- Track a content fingerprint of the data the self-learning fits read.
--
-- acwr_fit_data_changed_since_last_fit compared MAX(workouts.started_at) /
-- MAX(sleep.night_date) / MAX(cardio_sessions.date) against MAX(fitted_at): it
-- answers "is there data NEWER than the last fit", which is not the same question
-- as "has the data the fit read changed". A correction to existing rows advances
-- no max timestamp, so the guard reports "nothing new" and the fit keeps serving
-- parameters derived from values that no longer exist.
--
-- That is not hypothetical: on 2026-07-25 nine nights of sleep had their ts_out
-- repaired (679817d), and personal_sleep_bands / personal_acwr_bands — fitted at
-- 04:14 that morning, before the repair — would not have re-fitted until a night
-- newer than the fit timestamp arrived, roughly two days later.
--
-- One row per fit family, holding a hash over the actual column values each fit
-- consumes. Rows already fitted before this table existed have no fingerprint,
-- which reads as "cannot prove unchanged" and re-fits once.

CREATE TABLE IF NOT EXISTS fit_input_state (
    fit_name    VARCHAR PRIMARY KEY,
    fingerprint VARCHAR NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);
