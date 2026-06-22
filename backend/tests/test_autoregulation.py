from __future__ import annotations

from datetime import date

from shc.training.autoregulation import (
    EMPHASIS_MUSCLES,
    _decide,
    _protein_gate,
    _session_split,
    deload_check,
    weekly_prescription,
    MusclePrescription,
)
from shc.training.mesocycle import _iso_week_start
from shc.training.volume import MuscleVolume

# Landmarks used across cases: chest 10/16/22, biceps 8/14/20, quads 8/14/20.


def _d(muscle, current, perf, soreness=0.0, cond=None, mev=10, mav=16, mrv=22):
    # These cases exercise the RP set-progression tree in isolation. The #1/#10
    # confidence/accuracy gate is a separate layer that shrinks adds toward zero
    # when there is no signal (confidence=0, scored_weeks=0 → factor 0.0); pass a
    # clearing confidence so the tree's add/cut/hold decision is what's asserted,
    # not the suppression layer (which has its own coverage below).
    #
    # Emphasis is now resolved by the CALLER (#3/#26 — dynamic, via
    # _resolve_emphasis) rather than inside _decide. With no physique signal the
    # caller's emphasis set is just the biceps/glutes prior, so mirror that here
    # to keep the emphasis cases (biceps/glutes) genuinely exercising the
    # emphasis branch instead of silently falling through to the default.
    return _decide(
        muscle,
        current,
        mev,
        mav,
        mrv,
        perf,
        soreness,
        cond,
        emphasis=muscle in EMPHASIS_MUSCLES,
        confidence=0.6,
        scored_weeks=4,
    )


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
    # Bug 2 fix: floor is round(mev*0.4)=4, not mev=10.
    # round(18*0.5)=9, max(4, 9)=9 — real deload below MEV so fatigue clears.
    assert dl.target_sets == 9


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
    # New fields
    assert isinstance(rx.session_split, list)
    assert isinstance(rx.protein_gate, dict)
    assert "target" in rx.protein_gate


def _make_rx(muscle: str, target: int, action: str = "add") -> MusclePrescription:
    return MusclePrescription(
        muscle=muscle, current_sets=float(target - 1), target_sets=target,
        delta=1, action=action, reason="test",
    )


# ── _session_split ────────────────────────────────────────────────────────────


def test_session_split_upper_muscles_on_upper_days() -> None:
    rx = [_make_rx("biceps", 12), _make_rx("chest", 10)]
    split = _session_split(rx)
    # #18 contract: label and weekday are SEPARATE keys (session="Upper-A",
    # weekday="Tue"), not a combined "Upper-A (Tue)" string.
    upper = [(s["session"], s["weekday"]) for s in split if s["region"] == "upper"]
    assert ("Upper-A", "Tue") in upper or ("Upper-B", "Thu") in upper
    # No biceps or chest on lower days
    for sess in split:
        if "Lower" in sess["session"]:
            assert all(e["muscle"] not in ("biceps", "chest") for e in sess["muscles"])


def test_session_split_lower_muscles_on_lower_days() -> None:
    rx = [_make_rx("quads", 10), _make_rx("hamstrings", 8)]
    split = _session_split(rx)
    for sess in split:
        if "Upper" in sess["session"]:
            assert all(e["muscle"] not in ("quads", "hamstrings") for e in sess["muscles"])


def test_session_split_respects_10_set_ceiling() -> None:
    # 17 biceps sets → should be split across 2 upper sessions, each ≤10.
    rx = [_make_rx("biceps", 17)]
    split = _session_split(rx)
    for sess in split:
        for entry in sess["muscles"]:
            assert entry["sets"] <= 10, f"{sess['session']} has {entry['sets']} biceps sets > 10"


def test_session_split_zero_target_excluded() -> None:
    rx = [_make_rx("abs", 0)]
    split = _session_split(rx)
    for sess in split:
        assert not any(e["muscle"] == "abs" for e in sess["muscles"])


# ── _protein_gate ─────────────────────────────────────────────────────────────


def test_protein_gate_no_data_returns_none_adequate(conn) -> None:
    result = _protein_gate(conn)
    assert result["adequate"] is None
    assert result["days_logged"] == 0
    assert "note" in result


def test_protein_gate_adequate_when_above_target(conn) -> None:
    from datetime import timedelta
    today = date.today()
    for i in range(5):
        conn.execute(
            "INSERT INTO daily_checkin (date, created_at, protein_grams) VALUES (?, now(), ?)",
            [(today - timedelta(days=i)).isoformat(), 250],
        )
    result = _protein_gate(conn)
    assert result["adequate"] is True
    assert result["avg_7d"] == 250


def test_protein_gate_inadequate_when_below_target(conn) -> None:
    from datetime import timedelta
    today = date.today()
    for i in range(6):
        conn.execute(
            "INSERT INTO daily_checkin (date, created_at, protein_grams) VALUES (?, now(), ?)",
            [(today - timedelta(days=i)).isoformat(), 150],  # 150g < 80% of 239 = 191g
        )
    result = _protein_gate(conn)
    assert result["adequate"] is False
    assert "note" in result and result["note"]
