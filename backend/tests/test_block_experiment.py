from __future__ import annotations

import hashlib
from datetime import date, timedelta

from shc import block_experiment as be

AFTER = date(2027, 2, 1)
L, R = be.EXERCISE["left"], be.EXERCISE["right"]
BASE_KG = 20.0


def _build(
    seed,
    *,
    placebo=(5.0, 7.0),
    dose_gap=6.0,
    final_gap=6.0,
    right_per_session=7,
    left_per_session=4,
    deload_extra=False,
) -> None:
    """Two sessions a week (Tue/Thu). Gap is right-over-left in test-set weight."""
    weeks = be._weeks()
    for w in weeks:
        if w == be.DELOAD_WEEK and not deload_extra:
            continue
        for i, off in enumerate((1, 3)):
            if w == be.PLACEBO_WEEK:
                if i >= len(placebo):
                    continue
                gap, nr, nl = placebo[i], 4, 4
            else:
                gap = final_gap if w in be.SCORED_WEEKS else dose_gap
                nr = right_per_session * (3 if w == be.DELOAD_WEEK else 1)
                nl = left_per_session
            day = w + timedelta(days=off)
            seed.workout(day, L, [(BASE_KG, 10)] * nl, rpe=None)
            seed.workout(day, R, [(BASE_KG * (1 + gap / 100), 10)] * nr, rpe=None)


def test_coin_rederived_from_slug() -> None:
    digest = hashlib.sha256(be.SLUG.encode()).hexdigest()
    assert int(digest[-1], 16) % 2 == 1
    assert be.high_arm(be.SLUG) == "right" == be.HIGH_ARM


def test_supported(conn, seed) -> None:
    _build(seed, final_gap=9.5)
    out = be.score(conn, AFTER)
    assert out["verdict"] == "supported", out["reason"]
    assert out["change"] == 3.5
    assert out["placebo_sd"] == 1.414
    assert out["delivery"]["delivered"] is True


def test_ruled_out(conn, seed) -> None:
    _build(seed, final_gap=6.5)
    assert be.score(conn, AFTER)["verdict"] == "ruled_out"


def test_inconclusive_between_bounds(conn, seed) -> None:
    _build(seed, final_gap=8.5)  # change 2.5: above +2 but not above 2 x SD (2.83)
    assert be.score(conn, AFTER)["verdict"] == "inconclusive"


def test_not_delivered(conn, seed) -> None:
    _build(seed, final_gap=9.5, right_per_session=4)  # right averages 8 sets
    out = be.score(conn, AFTER)
    assert out["verdict"] == "not_delivered"
    assert out["delivery"]["avg_right_sets"] == 8.0


def test_pending_before_window_closes(conn, seed) -> None:
    _build(seed, final_gap=9.5)
    out = be.score(conn, date(2027, 1, 31))
    assert out["verdict"] == "pending" and out["reason"]


def test_deload_week_excluded(conn, seed) -> None:
    _build(seed, final_gap=9.5, deload_extra=True)
    out = be.score(conn, AFTER)
    assert be.DELOAD_WEEK.isoformat() not in out["delivery"]["dose_weeks"]
    assert out["delivery"]["avg_right_sets"] == 14.0
    row = next(r for r in out["weekly"] if r["week"] == be.DELOAD_WEEK.isoformat())
    assert row["phase"] == "deload" and row["right_sets"] == 42


def test_session_missing_an_arm_is_skipped(conn, seed) -> None:
    _build(seed, final_gap=9.5)
    seed.workout(date(2027, 1, 19), R, [(99.0, 10)], rpe=None)  # right only, odd weight
    seed.workout(date(2027, 1, 20), L, [(1.0, 10)], rpe=None)  # left only
    out = be.score(conn, AFTER)
    last = next(r for r in out["weekly"] if r["week"] == "2027-01-18")
    assert last["sessions_with_both_arms"] == 2
    assert out["change"] == 3.5


def test_sd_needs_two_placebo_sessions(conn, seed) -> None:
    _build(seed, placebo=(6.0,), final_gap=12.0)
    out = be.score(conn, AFTER)
    assert out["placebo_sd"] is None
    assert out["verdict"] == "inconclusive"


def test_warmup_is_not_the_test_set(conn, seed) -> None:
    _build(seed, final_gap=9.5)
    day = date(2027, 1, 19)
    seed.workout(day, L, [(5.0, 10)], rpe=None, is_warmup=True)
    seed.workout(day, R, [(5.0, 10)], rpe=None, is_warmup=True)
    assert be.score(conn, AFTER)["change"] == 3.5


def test_rerun_is_identical(conn, seed) -> None:
    _build(seed, final_gap=9.5)
    assert be.score(conn, AFTER) == be.score(conn, AFTER)
