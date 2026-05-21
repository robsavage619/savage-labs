from __future__ import annotations

import pytest

from shc.ai.workout_planner import GateViolation, validate_plan


def _plan(intensity="low", target_rpe=6, exercises=None):
    return {
        "readiness_tier": "yellow",
        "recommendation": {
            "intensity": intensity,
            "focus": "test",
            "rationale": "x",
            "estimated_duration_min": 40,
            "target_rpe": target_rpe,
        },
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
LOW_STATE = {"gates": {"max_intensity": "low", "deload_required": False,
                       "forbid_muscle_groups": [], "reasons": []}}
HIGH_STATE = {"gates": {"max_intensity": "high", "deload_required": False,
                        "forbid_muscle_groups": [], "reasons": []}}
DELOAD_STATE = {"gates": {"max_intensity": "low", "deload_required": True,
                          "forbid_muscle_groups": [], "reasons": []}}


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
    p = _plan(intensity="high", target_rpe=9,
              exercises=[_ex("Bench Press (Barbell)", 95, "6", rpe_target=9, rest_seconds=240)])
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


def test_deload_requires_low_rpe() -> None:
    p = _plan(intensity="moderate", target_rpe=9, exercises=[_ex("Face Pull", 40, "8")])
    with pytest.raises(GateViolation):
        validate_plan(p, state=DELOAD_STATE, e1rm_ceilings=CEIL)
