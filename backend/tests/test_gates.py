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
        "Low Cable Fly Crossovers",  # the bug: old "primary" was this
        "Hammerstrength Shoulder Press",
        "Leg Extension (Machine)",
        "Lateral Raise (Dumbbell)",  # isolation, not a strength pattern
        "Goblet Squat",  # grip-capped load
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


def test_load_cap_rest_is_most_conservative() -> None:
    """A "rest"-gated day trained via an override must NOT fall through to the
    103% high-day default — it needs its own, more conservative cap (below
    deload's 70%), since the underlying gate state is still "rest" even when
    the override lets a "low" plan clear the intensity check."""
    assert load_cap_pct({"max_intensity": "rest"}) == 60
    assert load_cap_pct({"max_intensity": "rest"}) < load_cap_pct({"deload_required": True})


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
    g = _gates(
        rec,
        sleep,
        load,
        chk,
        readiness,
        -6.0,
        deload_cooldown=False,
        e1rm_lift="Bench Press (Barbell)",
    )
    assert g.deload_required is True
    assert "Bench Press (Barbell)" in g.deload_reason


def test_deload_suppressed_during_cooldown() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    g = _gates(
        rec,
        sleep,
        load,
        chk,
        readiness,
        -34.2,
        deload_cooldown=True,
        e1rm_lift="Bench Press (Barbell)",
    )
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


def test_acwr_rest_threshold_uncoupled_scale() -> None:
    # Bands recalibrated to the uncoupled ACWR scale (M2): rest above 2.0.
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 2.1  # resistance arm gates intensity (pooled is display-only)
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "rest"


def test_acwr_low_threshold_uncoupled_scale() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.85
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "low"


def test_acwr_moderate_threshold_uncoupled_scale() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.6
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "moderate"


def test_acwr_below_moderate_leaves_high() -> None:
    # 1.4 was "moderate" on the coupled scale; on the uncoupled scale it's normal.
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.4
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "high"


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


# ── RPE-scaled rest gates + pickleball clock + ACWR band floor ───────────────


def test_easy_pull_session_needs_only_one_day() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_pull = 1
    load.last_rpe_pull = 6.0  # submaximal — threshold drops 2d → 1d
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "pull" not in g.forbid_muscle_groups


def test_hard_pull_session_keeps_48h_gate() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_pull = 1
    load.last_rpe_pull = 8.5
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "pull" in g.forbid_muscle_groups


def test_unknown_rpe_keeps_conservative_gate() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_pull = 1
    load.last_rpe_pull = None
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "pull" in g.forbid_muscle_groups


def test_easy_legs_session_needs_two_days() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_legs = 2
    load.last_rpe_legs = 6.0  # 3d → 2d
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "legs" not in g.forbid_muscle_groups


def test_same_day_pickleball_forbids_legs() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_pickleball = 0
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "legs" in g.forbid_muscle_groups


def test_yesterday_pickleball_leaves_legs_open() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.days_since_pickleball = 1
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert "legs" not in g.forbid_muscle_groups


def test_personal_acwr_bands_floored_at_population(conn) -> None:
    """A THIN-sample fitted band tighter than the population default must not
    tighten the gate — below _ACWR_TIGHTEN_MIN_WEEKS personal bands may only
    loosen (the fitted percentiles are biased low by low-volume history).

    Note: the sample count here is intentionally below the tighten bar. A
    well-sampled band IS allowed to tighten — see
    test_personal_acwr_bands_tighten_when_well_sampled."""
    for name, value in (("rest", 1.96), ("low", 1.48), ("mod", 1.2)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 12, now())",
            [name, value],
        )
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.88, 12, now())"
    )
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.44  # above the tight personal 1.2, below population 1.5
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"


def test_personal_acwr_caps_never_tighten_below_population(conn) -> None:
    """The MODERATE/LOW intensity caps are absolute safety ceilings, not
    homeostats. Even when well-sampled (≥ _ACWR_TIGHTEN_MIN_WEEKS), a personal
    cap fitted below population (mod 1.2 < 1.5) must NOT tighten the gate — it
    may only ever loosen above population. Otherwise the percentile-of-self fit
    gates ordinary progressive overload as a fatigue spike."""
    for name, value in (("rest", 1.96), ("low", 1.48), ("mod", 1.2)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 50, now())",
            [name, value],
        )
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.88, 50, now())"
    )
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.44  # above the tight personal mod (1.2), below population (1.5)
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"  # cap floored at population — not tightened


def test_personal_acwr_rest_gate_still_personalizes(conn) -> None:
    """REST is the true danger gate, not a progression cap, so a well-sampled
    personal REST band MAY still tighten below the population default (2.0)."""
    for name, value in (("rest", 1.96), ("low", 1.48), ("mod", 1.2)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 50, now())",
            [name, value],
        )
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.88, 50, now())"
    )
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    load.resistance_acwr = 1.97  # above personal rest (1.96), below population rest (2.0)
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "rest"


# ── Personal sleep-architecture bands (OSA baseline, not an acute flag) ──────


def test_population_disturbance_threshold_fires_without_personal_band() -> None:
    """Sanity check the population default (>=12) is what fires with no conn/history."""
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.disturbance_count_last = 14
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "moderate"
    assert any("fragmented night" in r for r in g.reasons)


def test_population_cycle_threshold_fires_without_personal_band() -> None:
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.sleep_cycle_count_last = 2
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "moderate"
    assert any("fragmented architecture" in r for r in g.reasons)


def _insert_sleep_bands(conn, disturbance_p80: float, cycle_p20: float) -> None:
    """read_sleep_bands requires BOTH metrics present (mirrors read_acwr_bands'
    all-4-or-none contract) — always insert both rows even when a test only
    exercises one of the two gates."""
    conn.execute(
        "INSERT INTO personal_sleep_bands (metric, threshold_name, value, sample_nights, fitted_at)"
        " VALUES ('disturbance_count', 'p80', ?, 40, now())",
        [disturbance_p80],
    )
    conn.execute(
        "INSERT INTO personal_sleep_bands (metric, threshold_name, value, sample_nights, fitted_at)"
        " VALUES ('sleep_cycle_count', 'p20', ?, 40, now())",
        [cycle_p20],
    )


def test_personal_disturbance_band_loosens_for_chronic_osa_baseline(conn) -> None:
    """A personal p80 fitted well above the population default (e.g. Rob's
    OSA-driven nightly norm of ~14) should stop 14 disturbances from firing —
    it's normal for him, not a fragmented-night flag."""
    _insert_sleep_bands(conn, disturbance_p80=18.0, cycle_p20=2.0)
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.disturbance_count_last = 14
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"


def test_personal_disturbance_band_never_tightens_below_population(conn) -> None:
    """Even if a personal fit comes in BELOW the population default (unusual,
    thin/atypical sample), the gate must not get stricter than 12 — loosen-only,
    same treatment as the ACWR LOW/MOD caps."""
    _insert_sleep_bands(conn, disturbance_p80=8.0, cycle_p20=2.0)
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.disturbance_count_last = 10  # above personal 8, below population 12
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"


def test_personal_cycle_band_loosens_for_chronic_osa_baseline(conn) -> None:
    """A personal p20 fitted well below the population default (e.g. Rob's
    OSA-driven nightly norm of ~2 cycles) should stop 2 cycles from firing —
    it's normal for him, not a fragmented-architecture flag."""
    _insert_sleep_bands(conn, disturbance_p80=18.0, cycle_p20=2.0)
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.sleep_cycle_count_last = 2
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"


def test_personal_cycle_band_never_tightens_above_population(conn) -> None:
    """Even if a personal fit comes in ABOVE the population default (unusual,
    thin/atypical sample), the gate must not get stricter than <4 — loosen-only."""
    _insert_sleep_bands(conn, disturbance_p80=18.0, cycle_p20=5.0)
    rec, sleep, load, chk, readiness = _baseline_gate_inputs()
    sleep.sleep_cycle_count_last = 4  # below personal 5, at population floor 4 (not < 4)
    g = _gates(rec, sleep, load, chk, readiness, None, conn=conn)
    assert g.max_intensity == "high"
