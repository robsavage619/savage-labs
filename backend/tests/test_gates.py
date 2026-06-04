from __future__ import annotations

import pytest

from shc.ai.workout_planner import load_cap_pct
from shc.metrics import (
    CheckinMetrics,
    ReadinessSnapshot,
    RecoveryMetrics,
    SleepMetrics,
    TrainingLoadMetrics,
    _gates,
    _is_strength_lift,
)

# ── _is_strength_lift ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name",
    [
        "Standing Military Press (Barbell)",
        "Bench Press (Dumbbell)",
        "Romanian Deadlift (Dumbbell)",
        "Split Squat (Dumbbell)",
        "Front Squat",
        "Bent Over Row (Barbell)",
    ],
)
def test_strength_lift_accepts_free_weight_compounds(name: str) -> None:
    assert _is_strength_lift(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Low Cable Fly Crossovers",      # the bug: old "primary" was this
        "Hammerstrength Shoulder Press",
        "Leg Extension (Machine)",
        "Lateral Raise (Dumbbell)",      # isolation, not a strength pattern
        "Goblet Squat",                  # grip-capped load
        "Chin Up (Assisted)",
        "Lat Pulldown (Cable)",
    ],
)
def test_strength_lift_rejects_machines_cables_isolation(name: str) -> None:
    assert _is_strength_lift(name) is False


# ── load_cap_pct ─────────────────────────────────────────────────────────────

def test_load_cap_deload_is_lowest() -> None:
    assert load_cap_pct({"deload_required": True, "max_intensity": "low"}) == 70


def test_load_cap_by_intensity() -> None:
    assert load_cap_pct({"max_intensity": "low"}) == 78
    assert load_cap_pct({"max_intensity": "moderate"}) == 90
    assert load_cap_pct({"max_intensity": "high"}) == 103


def test_high_day_cap_allows_progressive_overload() -> None:
    """A high day must sit above 100% so a new e1RM peak isn't rejected."""
    assert load_cap_pct({"max_intensity": "high"}) > 100


def test_deload_overrides_intensity_in_cap() -> None:
    # deload flag wins even if max_intensity says moderate
    assert load_cap_pct({"deload_required": True, "max_intensity": "moderate"}) == 70


# ── _gates deload trigger (the loop we fixed) ────────────────────────────────

def _baseline_gate_inputs():
    return (
        RecoveryMetrics(),
        SleepMetrics(),
        TrainingLoadMetrics(),
        CheckinMetrics(),
        ReadinessSnapshot(tier="green"),
    )


def test_deload_fires_on_regression_when_not_in_cooldown() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(rec, sleep, load, chk, readiness, -6.0, deload_cooldown=False,
               e1rm_lift="Bench Press (Barbell)")
    assert g.deload_required is True
    assert "Bench Press (Barbell)" in g.deload_reason


def test_deload_suppressed_during_cooldown() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(rec, sleep, load, chk, readiness, -34.2, deload_cooldown=True,
               e1rm_lift="Bench Press (Barbell)")
    assert g.deload_required is False
    assert g.deload_reason is None
    # regression is still recorded for transparency
    assert g.e1rm_regression_4wk_pct == -34.2
    assert any("suppressed" in r for r in g.reasons)


def test_no_deload_when_regression_above_threshold() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(rec, sleep, load, chk, readiness, -1.0, deload_cooldown=False)
    assert g.deload_required is False


def test_no_deload_when_regression_none() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(rec, sleep, load, chk, readiness, None, deload_cooldown=False)
    assert g.deload_required is False
    assert g.e1rm_regression_4wk_pct is None


# ── a couple of sanity checks on the legitimate intensity gates ──────────────

def test_skin_temp_elevation_caps_low() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    rec.skin_temp_delta = 1.0  # °C above baseline
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "low"


def test_illness_flag_forces_rest() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    chk.illness_flag = True
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "rest"


def test_clean_inputs_leave_high() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "high"
    assert g.deload_required is False


def test_acwr_above_1_65_forces_rest() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.7  # lifting load gates intensity (pooled acwr is display-only)
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "rest"


def test_acwr_1_5_to_1_65_caps_low() -> None:
    # Concurrent athletes routinely run 1.5–1.65; graduated step, not full rest.
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.55
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "low"


def test_acwr_above_1_3_caps_moderate() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.4
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "moderate"


def test_acwr_in_safe_band_leaves_high() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.acwr = 1.1
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "high"


def test_recent_leg_training_forbids_legs() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_legs = 1  # < 2-day threshold for legs
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "legs" in g.forbid_muscle_groups
