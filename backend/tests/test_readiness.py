from __future__ import annotations

import pytest

from shc.metrics import (
    BETA_BLOCKER_WEIGHTS,
    DEFAULT_WEIGHTS,
    CheckinMetrics,
    RecoveryMetrics,
    SleepMetrics,
    _hrv_subscore,
    _is_beta_blocker,
    _readiness_snapshot,
    _rhr_subscore,
    _sleep_subscore,
    _subj_subscore,
    _tier,
    muscle_group,
)

# ── _is_beta_blocker ─────────────────────────────────────────────────────────

def test_beta_blocker_matches_propranolol_case_insensitive() -> None:
    assert _is_beta_blocker(["Propranolol (Inderal) 10 mg PRN"]) is True
    assert _is_beta_blocker(["metoprolol", "lisinopril"]) is True


def test_beta_blocker_false_for_non_bb_meds() -> None:
    assert _is_beta_blocker(["Escitalopram", "Flonase", "Grass Pollen"]) is False
    assert _is_beta_blocker([]) is False


# ── _hrv_subscore ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "sigma,expected",
    [(None, None), (0.0, 50.0), (1.0, 75.0), (2.0, 100.0), (-2.0, 0.0), (5.0, 100.0)],
)
def test_hrv_subscore(sigma, expected) -> None:
    assert _hrv_subscore(sigma) == expected


# ── _rhr_subscore ────────────────────────────────────────────────────────────

def test_rhr_subscore_none_inputs() -> None:
    assert _rhr_subscore(None, 50) is None
    assert _rhr_subscore(50, None) is None
    assert _rhr_subscore(50, 0) is None  # falsy baseline


def test_rhr_subscore_at_baseline_is_midpoint() -> None:
    assert _rhr_subscore(50, 50) == 50.0


def test_rhr_subscore_lower_rhr_scores_higher() -> None:
    assert _rhr_subscore(45, 50) == 100.0   # 10% below → clamps high
    assert _rhr_subscore(55, 50) == 0.0      # 10% above → clamps low


# ── _subj_subscore ───────────────────────────────────────────────────────────

def test_subj_subscore_none_when_no_inputs() -> None:
    assert _subj_subscore(None, None, None) is None


def test_subj_subscore_inverts_stress_and_soreness() -> None:
    # energy 8 → 80; stress 2 → 80; soreness 2 → 80
    assert _subj_subscore(8, 2, 2) == 80.0
    # high stress drags it down
    assert _subj_subscore(8, 8, 2) == pytest.approx((80 + 20 + 80) / 3)


# ── _sleep_subscore ──────────────────────────────────────────────────────────

def test_sleep_subscore_none_hours() -> None:
    assert _sleep_subscore(None, 0.2, 97) is None


def test_sleep_subscore_full_marks() -> None:
    assert _sleep_subscore(8.0, 0.20, 97) == 100.0


def test_sleep_subscore_blended() -> None:
    # hours 6 → dur 50; deep 0.15 → 75; spo2 93 → 40
    assert _sleep_subscore(6.0, 0.15, 93) == pytest.approx(0.5 * 50 + 0.3 * 75 + 0.2 * 40)


def test_sleep_subscore_deep_falls_back_to_duration() -> None:
    # no deep%, no spo2 → deep_score=dur, spo2=(dur+deep)/2 → equals dur
    assert _sleep_subscore(8.0, None, None) == 100.0


# ── _tier ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "score,tier",
    [(None, None), (90, "green"), (67, "green"), (66.9, "yellow"), (34, "yellow"),
     (33.9, "red"), (0, "red")],
)
def test_tier_thresholds(score, tier) -> None:
    assert _tier(score) == tier


# ── _readiness_snapshot ──────────────────────────────────────────────────────

def test_readiness_none_when_no_components() -> None:
    snap = _readiness_snapshot(RecoveryMetrics(), SleepMetrics(), CheckinMetrics(),
                               beta_blocker=False)
    assert snap.score is None
    assert snap.tier is None


def test_readiness_single_component_equals_that_component() -> None:
    # only HRV present → re-normalized weight is 1.0 → score == hrv subscore
    rec = RecoveryMetrics(hrv_sigma=1.0)  # subscore 75
    snap = _readiness_snapshot(rec, SleepMetrics(), CheckinMetrics(), beta_blocker=False)
    assert snap.score == 75.0
    assert snap.tier == "green"


def test_readiness_uses_default_weights_without_beta_blocker() -> None:
    snap = _readiness_snapshot(RecoveryMetrics(hrv_sigma=0.0), SleepMetrics(score=80),
                               CheckinMetrics(), beta_blocker=False)
    assert snap.weights == DEFAULT_WEIGHTS
    assert snap.beta_blocker_adjusted is False


def test_readiness_reweights_under_beta_blocker() -> None:
    """Beta-blocker blunts HRV, so HRV weight drops and sleep/RHR rise."""
    rec = RecoveryMetrics(hrv_sigma=0.0)
    sleep = SleepMetrics(score=80)
    default = _readiness_snapshot(rec, sleep, CheckinMetrics(), beta_blocker=False)
    bb = _readiness_snapshot(rec, sleep, CheckinMetrics(), beta_blocker=True)
    assert bb.weights == BETA_BLOCKER_WEIGHTS
    assert bb.beta_blocker_adjusted is True
    # With low HRV (50) and good sleep (80), down-weighting HRV raises the score.
    assert bb.score > default.score


# ── muscle_group ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "exercise,group",
    [
        ("Bench Press (Barbell)", "push"),
        ("Overhead Press (Dumbbell)", "push"),
        ("Triceps Rope Pushdown", "push"),
        ("Bent Over Row (Barbell)", "pull"),
        ("Bicep Curl (Cable)", "pull"),
        ("Lat Pulldown (Cable)", "pull"),
        # Deadlift variants classify as pull (posterior-chain), checked before legs.
        ("Romanian Deadlift (Dumbbell)", "pull"),
        ("Goblet Squat", "legs"),
        ("Standing Calf Raise (Machine)", "legs"),
        ("Plank", "core"),
        ("Walking", "other"),
    ],
)
def test_muscle_group_classification(exercise, group) -> None:
    assert muscle_group(exercise) == group
