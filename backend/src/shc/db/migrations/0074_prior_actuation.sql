-- Structured actuation fields for n-of-1 experiment priors.
--
-- A CONFIRMED experiment previously reached only the LLM prompt as prose
-- (workout_planner.py's "CONFIRMED PERSONAL EXPERIMENTS" section) — a real,
-- causal, self-tested effect that changed NO deterministic decision. This
-- adds a CLOSED-VOCABULARY actuation target, declared at PREREGISTRATION time
-- (before any data is seen, so the target can't be picked to fit a result),
-- so a CONFIRMED verdict can move one concrete, pre-bounded decision variable.
--
-- Declared on `experiments` (the immutable intent, set before data collection);
-- copied onto `experiment_prior` only when a study actually CONFIRMS, so a
-- consumer (autoregulation._decide / metrics._gates) reads one self-contained
-- table with no join back to `experiments` needed. Retraction (active=FALSE,
-- already supported) removes the actuation the same way it removes the prior.
--
-- target_kind:
--   'volume_target' — target_key is a canonical muscle name; direction/
--     magnitude_pct/cap_pct scale that muscle's weekly set target while active.
--   'gate_loosen'   — target_key is a gate name; may only LOOSEN a safety
--     threshold, never tighten, and never past the population ceiling.
-- Legacy priors (preregistered before this migration) have NULL actuation
-- fields and stay prompt-only — no behavior change for them.

ALTER TABLE experiments ADD COLUMN IF NOT EXISTS actuation_target_kind VARCHAR;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS actuation_target_key VARCHAR;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS actuation_direction VARCHAR;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS actuation_magnitude_pct DOUBLE;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS actuation_cap_pct DOUBLE;

ALTER TABLE experiment_prior ADD COLUMN IF NOT EXISTS target_kind VARCHAR;
ALTER TABLE experiment_prior ADD COLUMN IF NOT EXISTS target_key VARCHAR;
ALTER TABLE experiment_prior ADD COLUMN IF NOT EXISTS direction VARCHAR;
ALTER TABLE experiment_prior ADD COLUMN IF NOT EXISTS magnitude_pct DOUBLE;
ALTER TABLE experiment_prior ADD COLUMN IF NOT EXISTS cap_pct DOUBLE;
