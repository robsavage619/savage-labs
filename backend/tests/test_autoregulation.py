from __future__ import annotations

from datetime import date

from shc.training.autoregulation import _decide, deload_check, weekly_prescription
from shc.training.mesocycle import _iso_week_start
from shc.training.volume import MuscleVolume

# Landmarks used across cases: chest 10/16/22, biceps 8/14/20, quads 8/14/20.


def _d(muscle, current, perf, soreness=0.0, cond=None, mev=10, mav=16, mrv=22):
    return _decide(muscle, current, mev, mav, mrv, perf, soreness, cond)


def test_progressing_recovered_adds():
    rx = _d("chest", current=12, perf=5)
    assert rx.action == "add"
    assert rx.target_sets == 13  # +1, non-emphasis


def test_emphasis_muscle_adds_two():
    rx = _d("biceps", current=12, perf=5, mev=8, mav=14, mrv=20)
    assert rx.action == "add"
    assert rx.delta == 2  # emphasis ramps faster


def test_regressing_cuts():
    rx = _d("chest", current=18, perf=2)
    assert rx.action == "cut"
    assert rx.target_sets < 18


def test_under_recovered_backs_off():
    rx = _d("chest", current=16, perf=4, soreness=2.5)
    assert rx.action == "cut"


def test_at_mrv_holds():
    rx = _d("chest", current=22, perf=5)
    assert rx.action == "hold"
    assert rx.target_sets == 22


def test_leg_interference_holds_volume():
    rx = _d("quads", current=12, perf=5, cond=1.6, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert "ACWR" in rx.reason


def test_emphasis_below_floor_ramps_up():
    # Emphasis floor is the MEV-MAV midpoint (6+3=9), NOT MAV; ramp capped at
    # +2/week (MAX_WEEKLY_ADD), so 4 → 6 this week, not a jump to the floor.
    rx = _d("glutes", current=4, perf=None, mev=6, mav=12, mrv=16)
    assert rx.action == "add"
    assert rx.delta == 2


def test_emphasis_does_not_start_at_mav():
    # Regression guard for M3: an emphasis muscle sitting AT its midpoint floor
    # (8 + (14-8)//2 = 11) with no signal must HOLD — not chase MAV (14).
    rx = _d("biceps", current=11, perf=None, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert rx.target_sets == 11


def test_add_step_capped_at_two():
    # M10: even a big desired jump (below-floor ramp) adds at most MAX_WEEKLY_ADD.
    rx = _d("chest", current=2, perf=None, mev=10, mav=16, mrv=22)
    assert rx.action == "add"
    assert rx.delta == 2  # 2 → 4, not 2 → 10


def test_action_never_contradicts_delta():
    # A held muscle must report delta 0 (the bug the endpoint surfaced).
    rx = _d("quads", current=0, perf=5, cond=1.9, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert rx.delta == 0


def test_stall_breaks_with_one_set():
    rx = _d("chest", current=14, perf=3)
    assert rx.action == "add"
    assert rx.delta == 1


def _mv(muscle, actual, mev=10, mav=16, mrv=22):
    return MuscleVolume(muscle, actual, mev, mav, mrv, "in range")


def test_deload_fires_on_broad_regression():
    perfs = {"chest": 2, "lats": 1, "quads": 2, "biceps": 4}
    report = [_mv(m, 12) for m in perfs]
    dl = deload_check(perfs, report)
    assert dl["recommended"] is True
    assert "regressing" in dl["reason"]


def test_deload_fires_when_many_at_mrv():
    perfs = {"chest": 4, "lats": 4, "quads": 4}
    report = [_mv("chest", 22), _mv("lats", 22), _mv("quads", 23)]
    dl = deload_check(perfs, report)
    assert dl["recommended"] is True
    assert "MRV" in dl["reason"]


def test_no_deload_without_systemic_signal():
    perfs = {"chest": 4, "lats": 2, "quads": 5}  # one regressing — below threshold
    report = [_mv(m, 12) for m in perfs]
    assert deload_check(perfs, report)["recommended"] is False


def test_regressing_below_mev_adds_not_cuts():
    # current=4 < MEV=10 while regressing (perf=2) → action must be add (toward MEV),
    # not cut (which would drive volume negative). Reason must not say "cut".
    rx = _d("traps", current=4, perf=2, mev=10, mav=16, mrv=22)
    assert rx.action == "add", f"expected add, got {rx.action}"
    assert rx.target_sets > 4, "target should be higher than current when below MEV"
    assert "cut" not in rx.reason.lower() or "build" in rx.reason.lower()


def test_regressing_above_mev_cuts():
    rx = _d("chest", current=18, perf=2)
    assert rx.action == "cut"
    assert rx.target_sets < 18


def test_decide_deload_halves_volume():
    rx = _d("chest", current=18, perf=5, mev=10, mav=16, mrv=22)
    assert rx.action == "add"  # sanity: normally it would grow
    dl = _decide("chest", 18, 10, 16, 22, perf=5, soreness=0.0, conditioning_acwr=None, deload=True)
    assert dl.action == "deload"
    assert dl.target_sets == 10  # round(18*0.5)=9, floored at MEV 10


def test_weekly_prescription_smoke(conn, seed):
    """End-to-end: prescription emits per-muscle calls from logged volume."""
    today = date.today()
    for wk in range(3):
        seed.workout(
            date.fromordinal(today.toordinal() - wk * 7), "Bicep Curl (Barbell)", [(20.0, 10)] * 4
        )

    rx = weekly_prescription(conn)

    assert rx.week_start == _iso_week_start(today)
    biceps = next((m for m in rx.muscles if m.muscle == "biceps"), None)
    assert biceps is not None
    assert biceps.emphasis is True
