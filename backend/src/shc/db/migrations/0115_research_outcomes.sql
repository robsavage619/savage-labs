-- The lab studies goal outcomes (strength, body mass, VO2 max), not just HRV.
-- A belief now carries the unit of its effect so the ledger can draw each one
-- on its own scale; NULL means "take it from the outcome feature". A backtest
-- that declines to score itself (no beliefs, too little history) says why.
ALTER TABLE research_beliefs ADD COLUMN IF NOT EXISTS unit VARCHAR;
ALTER TABLE research_forecast_skill ADD COLUMN IF NOT EXISTS reason VARCHAR;
