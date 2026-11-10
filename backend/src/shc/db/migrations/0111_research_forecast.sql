-- The forecaster: one live next-morning forecast per day, logged before the
-- reading exists and scored when it arrives, plus rolling-origin backtests.
-- forecast_gain is how much each belief improves the backtest's skill; a
-- belief that doesn't help is a candidate for demotion.
CREATE TABLE IF NOT EXISTS research_forecasts (
    target_date  DATE    NOT NULL,
    metric       VARCHAR NOT NULL,
    predicted    DOUBLE  NOT NULL,
    actual       DOUBLE,
    terms        VARCHAR,
    made_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (target_date, metric)
);

CREATE TABLE IF NOT EXISTS research_forecast_skill (
    run_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    metric     VARCHAR NOT NULL,
    skill      DOUBLE,
    n          INTEGER NOT NULL,
    rmse_lab   DOUBLE,
    rmse_base  DOUBLE,
    gains      VARCHAR,
    series     VARCHAR
);

ALTER TABLE research_beliefs ADD COLUMN IF NOT EXISTS forecast_gain DOUBLE;
