-- Migration 0062: Gate-override audit log.
--
-- `/api/workout/plan` previously had no way to train through the fatigue-model
-- max_intensity gate at all — even a deliberate, well-reasoned "yes, I know,
-- I want to train anyway" required silently editing the plan around the
-- validator. validate_plan() now accepts an override_reason that loosens
-- max_intensity by exactly one tier (never touching forbid_muscle_groups,
-- deload_required, or the clinical contraindication guard). This table is
-- the audit trail for when that override is actually exercised, so a pattern
-- of frequent overrides is visible rather than invisible.

CREATE TABLE IF NOT EXISTS gate_overrides (
    id                  VARCHAR PRIMARY KEY,
    plan_date           DATE NOT NULL,
    requested_intensity VARCHAR NOT NULL,
    gate_max_intensity  VARCHAR NOT NULL,
    reason              VARCHAR NOT NULL,
    gates_bypassed_json VARCHAR NOT NULL,  -- JSON array of the gate.reasons in effect
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
