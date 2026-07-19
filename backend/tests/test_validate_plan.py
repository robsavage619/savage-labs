from __future__ import annotations

import duckdb
import pytest

from shc.ai.workout_planner import (
    _RELATIVE_CLINICAL_CAP,
    GateViolation,
    _clinical_volume_cap,
    validate_plan,
)

_UNSET = object()


def _plan(intensity="low", target_rpe=_UNSET, exercises=None):
    rec: dict = {
        "intensity": intensity,
        "focus": "test",
        "rationale": "x",
        "estimated_duration_min": 40,
    }
    if target_rpe is not _UNSET:
        rec["target_rpe"] = target_rpe
    return {
        "readiness_tier": "yellow",
        "recommendation": rec,
        "warmup": [{"name": "Walking", "sets": 1, "reps": 5}],
        "blocks": [{"label": "A", "exercises": exercises or []}],
        "cooldown": "walk",
        "clinical_notes": ["propranolol PRN; asthma"],
        "vault_insights": ["a", "b"],
    }


def _ex(name, weight_lbs, reps, **kw):
    return {
        "name": name,
        "sets": 3,
        "reps": reps,
        "weight_lbs": weight_lbs,
        "rpe_target": kw.get("rpe_target", 6),
        "rest_seconds": kw.get("rest_seconds", 120),
        "notes": "n",
    }


# ── schema validation ────────────────────────────────────────────────────────


def test_rejects_bad_readiness_tier() -> None:
    p = _plan(exercises=[_ex("Face Pull", 50, "8")])
    p["readiness_tier"] = "purple"
    with pytest.raises(ValueError):
        validate_plan(p)


def test_rejects_block_using_name_instead_of_label() -> None:
    p = _plan(exercises=[_ex("Face Pull", 50, "8")])
    del p["blocks"][0]["label"]
    p["blocks"][0]["name"] = "A"
    with pytest.raises(ValueError):
        validate_plan(p)


def test_rejects_missing_rest_seconds() -> None:
    ex = _ex("Face Pull", 50, "8")
    del ex["rest_seconds"]
    with pytest.raises(ValueError):
        validate_plan(_plan(exercises=[ex]))


# ── load-ceiling enforcement (fix #1) ────────────────────────────────────────

# Face Pull e1RM ~48 kg (~105 lb). low-day cap 78% → ceiling ~82 lb e1RM.
CEIL = {"Face Pull": 48.0, "Bench Press (Barbell)": 49.0}
LOW_STATE = {
    "gates": {
        "max_intensity": "low",
        "deload_required": False,
        "forbid_muscle_groups": [],
        "reasons": [],
    }
}
HIGH_STATE = {
    "gates": {
        "max_intensity": "high",
        "deload_required": False,
        "forbid_muscle_groups": [],
        "reasons": [],
    }
}
DELOAD_STATE = {
    "gates": {
        "max_intensity": "low",
        "deload_required": True,
        "forbid_muscle_groups": [],
        "reasons": [],
    }
}
REST_STATE = {
    "gates": {
        "max_intensity": "rest",
        "deload_required": False,
        "forbid_muscle_groups": ["legs"],
        "reasons": ["Resistance ACWR 2.04 > 1.87 — lifting fatigue spike, rest required"],
    }
}


def test_rejects_supramaximal_pseudo_deload() -> None:
    """The reported bug: hold near-max weight, add reps. 70lb×12 demands 98lb
    e1RM, over the deload ceiling."""
    p = _plan(exercises=[_ex("Face Pull", 70, "12")])
    with pytest.raises(GateViolation, match="max attempt"):
        validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL)


def test_accepts_load_under_ceiling() -> None:
    p = _plan(exercises=[_ex("Face Pull", 50, "8")])
    assert validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL) is True


def test_high_day_allows_progressive_overload() -> None:
    """A new-peak attempt on a high day must pass (cap > 100%)."""
    p = _plan(
        intensity="high",
        target_rpe=9,
        exercises=[_ex("Bench Press (Barbell)", 95, "6", rpe_target=9, rest_seconds=240)],
    )
    assert validate_plan(p, state=HIGH_STATE, e1rm_ceilings=CEIL) is True


def test_skips_null_weight_exercises() -> None:
    p = _plan(exercises=[_ex("Face Pull", None, "8")])
    assert validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL) is True


def test_skips_exercises_without_e1rm_record() -> None:
    p = _plan(exercises=[_ex("Brand New Lift", 500, "8")])
    assert validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL) is True


def test_parses_reps_from_each_side_string() -> None:
    # 70lb × 10/side still parses reps=10 → demand 93lb, over deload ceiling.
    p = _plan(exercises=[_ex("Face Pull", 70, "10 each side")])
    with pytest.raises(GateViolation):
        validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL)


# ── existing gate enforcement still holds ────────────────────────────────────


def test_intensity_exceeding_gate_rejected() -> None:
    p = _plan(intensity="high", target_rpe=9, exercises=[_ex("Face Pull", 50, "8")])
    with pytest.raises(GateViolation):
        validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL)


# ── override_reason (gate-override feature) ─────────────────────────────────


def test_rest_gate_rejects_low_intensity_without_override() -> None:
    p = _plan(intensity="low", exercises=[_ex("Face Pull", 40, "8")])
    with pytest.raises(GateViolation, match="rest"):
        validate_plan(p, state=REST_STATE, e1rm_ceilings=CEIL)


def test_override_reason_loosens_rest_gate_by_one_tier() -> None:
    """override_reason lets a "low" plan clear a "rest" gate — exactly one tier."""
    p = _plan(intensity="low", exercises=[_ex("Face Pull", 40, "8")])
    assert (
        validate_plan(
            p, state=REST_STATE, e1rm_ceilings=CEIL, override_reason="feel good, want to lift"
        )
        is True
    )


def test_override_reason_does_not_jump_two_tiers() -> None:
    """A "rest" gate loosens to "low" at most — "moderate" still rejected even
    with a reason. The override is a bounded concession, not a blank check."""
    p = _plan(intensity="moderate", target_rpe=7, exercises=[_ex("Face Pull", 40, "8")])
    with pytest.raises(GateViolation):
        validate_plan(
            p, state=REST_STATE, e1rm_ceilings=CEIL, override_reason="feel good, want to lift"
        )


def test_override_reason_does_not_bypass_forbidden_muscle_groups() -> None:
    """override_reason loosens the fatigue-model intensity cap only — it must
    NOT let a forbidden muscle group (here: legs, forbidden independent of
    today's sleep/ACWR signals) train through."""
    p = _plan(intensity="low", exercises=[_ex("Goblet Squat", 60, "8")])
    with pytest.raises(GateViolation, match="forbidden"):
        validate_plan(
            p, state=REST_STATE, e1rm_ceilings=CEIL, override_reason="feel good, want to lift"
        )


# ── override_muscle_groups (deliberate train-through of a recovery gate) ──────

FORBID_LEGS_STATE = {
    "gates": {
        "max_intensity": "moderate",
        "deload_required": False,
        "forbid_muscle_groups": ["legs"],
        "reasons": ["Legs 1d ago — needs ≥2d rest"],
    }
}
FORBID_PULL_STATE = {
    "gates": {
        "max_intensity": "moderate",
        "deload_required": False,
        "forbid_muscle_groups": ["pull"],
        "reasons": ["Pull 1d ago — needs ≥2d rest"],
    }
}


def test_muscle_group_override_allows_a_gated_group() -> None:
    """An explicit override_muscle_groups + reason lets a rested-gate group train."""
    p = _plan(intensity="low", exercises=[_ex("Goblet Squat", None, "8")])
    assert (
        validate_plan(
            p,
            state=FORBID_LEGS_STATE,
            e1rm_ceilings=CEIL,
            override_reason="deliberate light legs, feel great",
            override_muscle_groups=["legs"],
        )
        is True
    )


def test_muscle_group_override_requires_a_reason() -> None:
    """No silent bypass — overriding a recovery gate demands a recorded reason."""
    p = _plan(intensity="low", exercises=[_ex("Goblet Squat", None, "8")])
    with pytest.raises(ValueError, match="override_reason"):
        validate_plan(
            p, state=FORBID_LEGS_STATE, e1rm_ceilings=CEIL, override_muscle_groups=["legs"]
        )


def test_muscle_group_override_only_loosens_listed_groups() -> None:
    """Overriding one group must not unlock a different forbidden group."""
    p = _plan(intensity="low", exercises=[_ex("Goblet Squat", None, "8")])
    with pytest.raises(GateViolation, match="forbidden"):
        validate_plan(
            p,
            state=FORBID_LEGS_STATE,
            e1rm_ceilings=CEIL,
            override_reason="wrong group listed",
            override_muscle_groups=["push"],  # legs still blocked
        )


def test_hip_thrust_allowed_under_pull_forbid() -> None:
    """Hip Thrust is a fixed-back bridge, not a spinal hip-hinge — metrics._HINGE
    already excludes it (routes to legs/glutes, same as Glute Bridge). It must
    NOT be blocked when the pull gate forbids hinge patterns."""
    p = _plan(intensity="moderate", exercises=[_ex("Hip Thrust", None, "8")])
    assert validate_plan(p, state=FORBID_PULL_STATE, e1rm_ceilings=CEIL) is True


def test_rdl_still_rejected_under_pull_forbid() -> None:
    """Sanity check: removing Hip Thrust from the hinge list must not weaken
    the guard for genuine hip-hinge patterns. RDL classifies as the 'pull'
    group itself, so overriding that group is what isolates the
    hinge-specific check (the same setup test_muscle_group_override_does_not_
    unlock_hip_hinge below uses) — without an override RDL is caught earlier
    by the plain group-forbid check, which proves nothing about the hinge list."""
    p = _plan(intensity="moderate", exercises=[_ex("Romanian Deadlift (Dumbbell)", None, "8")])
    with pytest.raises(GateViolation, match="hinge"):
        validate_plan(
            p,
            state=FORBID_PULL_STATE,
            e1rm_ceilings=CEIL,
            override_reason="want some posterior work",
            override_muscle_groups=["pull"],
        )


def test_muscle_group_override_does_not_unlock_hip_hinge() -> None:
    """The hinge guard (#19) is an injury-pattern constraint, not a recovery
    window — overriding the pull group must NOT let a hinge through."""
    p = _plan(intensity="low", exercises=[_ex("Romanian Deadlift (Dumbbell)", None, "8")])
    with pytest.raises(GateViolation, match="hinge"):
        validate_plan(
            p,
            state=FORBID_PULL_STATE,
            e1rm_ceilings=CEIL,
            override_reason="want some posterior work",
            override_muscle_groups=["pull"],
        )


def test_override_reason_unused_when_plan_already_within_gate() -> None:
    """A reason present on a plan that's already within the true gate changes
    nothing — validate_plan just passes, same as with no reason at all."""
    p = _plan(intensity="low", exercises=[_ex("Face Pull", 50, "8")])
    assert validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL, override_reason="unused") is True


def test_deload_requires_low_rpe() -> None:
    p = _plan(intensity="moderate", target_rpe=9, exercises=[_ex("Face Pull", 40, "8")])
    with pytest.raises(GateViolation):
        validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL)


# ── target_rpe absent from recommendation (bug: defaulted to 10, tripped deload gate) ──


def test_deload_passes_when_target_rpe_absent_and_exercise_rpEs_low() -> None:
    """Recommendation omits target_rpe; gate must derive from exercise rpe_targets (≤7)."""
    p = _plan(intensity="low", exercises=[_ex("Face Pull", 30, "12", rpe_target=2)])
    assert validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL) is True


def test_deload_rejects_when_target_rpe_absent_and_exercise_rpes_high() -> None:
    """Recommendation omits target_rpe; derived max from exercise rpe_targets (>7) must reject."""
    p = _plan(intensity="low", exercises=[_ex("Face Pull", 30, "12", rpe_target=9)])
    with pytest.raises(GateViolation, match="RPE"):
        validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL)


# --- #21 deterministic clinical contraindication cap -------------------------


def _clinical_conn(conditions=(), labs=()):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE conditions (name VARCHAR, status VARCHAR, valid_to DATE)")
    conn.execute(
        "CREATE TABLE labs (name VARCHAR, value DOUBLE, ref_high DOUBLE, collected_at DATE)"
    )
    for name, status in conditions:
        conn.execute("INSERT INTO conditions VALUES (?, ?, NULL)", [name, status])
    for name, value, ref_high in labs:
        conn.execute("INSERT INTO labs VALUES (?, ?, ?, current_date)", [name, value, ref_high])
    return conn


def test_clinical_cap_absolute_cardiac_forbids_all() -> None:
    cap, reason = _clinical_volume_cap(
        _clinical_conn(conditions=[("Acute coronary syndrome", None)])
    )
    assert cap == 0
    assert reason is not None


def test_clinical_cap_absolute_critical_potassium() -> None:
    cap, reason = _clinical_volume_cap(_clinical_conn(labs=[("Potassium", 6.4, 5.2)]))
    assert cap == 0
    assert reason is not None


def test_clinical_cap_relative_acute_illness() -> None:
    cap, reason = _clinical_volume_cap(_clinical_conn(conditions=[("Influenza A", None)]))
    assert cap == _RELATIVE_CLINICAL_CAP
    assert reason is not None


def test_clinical_cap_relative_anemia() -> None:
    cap, reason = _clinical_volume_cap(_clinical_conn(labs=[("Hemoglobin", 9.1, 17.5)]))
    assert cap == _RELATIVE_CLINICAL_CAP
    assert reason is not None


def test_clinical_cap_clear_when_healthy() -> None:
    cap, reason = _clinical_volume_cap(_clinical_conn(labs=[("Hemoglobin", 14.2, 17.5)]))
    assert cap is None
    assert reason is None


def test_rep_range_enforced_rejects_out_of_band(conn) -> None:
    # Binding the sports-science layer: Incline Curl is curated for 10–20 reps;
    # a 3-rep grinder defeats the lengthened-isolation stimulus → rejected.
    state = {"gates": {"max_intensity": "high", "forbid_muscle_groups": [], "reasons": []}}
    plan = _plan(intensity="moderate", exercises=[_ex("Incline Curl (Dumbbell)", 30, "3")])
    with pytest.raises(GateViolation, match="evidence-based"):
        validate_plan(plan, state=state, conn=conn)


def test_rep_range_allows_in_band(conn) -> None:
    state = {"gates": {"max_intensity": "high", "forbid_muscle_groups": [], "reasons": []}}
    plan = _plan(intensity="moderate", exercises=[_ex("Incline Curl (Dumbbell)", 30, "12")])
    validate_plan(plan, state=state, conn=conn)  # in-band → no rep violation


def test_rep_range_high_end_of_prescribed_range_rejected(conn) -> None:
    """Incline Curl's window is 10-20 (+3 tolerance -> 23). A "20-25" prescription
    has an in-band LOW end (20) but its HIGH end (25) overshoots — must be caught
    on the range's high end, not just its first/low number."""
    state = {"gates": {"max_intensity": "high", "forbid_muscle_groups": [], "reasons": []}}
    plan = _plan(intensity="moderate", exercises=[_ex("Incline Curl (Dumbbell)", 30, "20-25")])
    with pytest.raises(GateViolation, match="evidence-based"):
        validate_plan(plan, state=state, conn=conn)


def test_load_ceiling_checked_against_high_end_of_rep_range() -> None:
    """A "10-12" prescription at 62lb passes the ceiling at 10 reps but breaches
    it at 12 (Face Pull e1RM 48kg, low-day ceiling ~82.5lb e1RM) — the ceiling
    must be evaluated at the range's high end (the heaviest-implied demand the
    athlete may actually execute), not just the range's first number."""
    p = _plan(exercises=[_ex("Face Pull", 62, "10-12")])
    with pytest.raises(GateViolation, match="max attempt"):
        validate_plan(p, state=LOW_STATE, e1rm_ceilings=CEIL)


def test_clinical_cap_db_error_fails_visible_not_silent() -> None:
    # Fail-visible hardening: a crashed contraindication query must NOT look like
    # "all clear" (cap=None, reason=None). It returns a reason so the caller
    # degrades conservatively and Rob sees why, instead of getting full intensity.
    conn = _clinical_conn()
    conn.execute("DROP TABLE conditions")  # force the conditions query to error
    cap, reason = _clinical_volume_cap(conn)
    assert cap is None
    assert reason is not None
    assert "failed" in reason.lower()
