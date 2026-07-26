from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc.ai.workout_planner import e1rm_by_exercise


def days_ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


def test_empty_when_no_data(conn, today: date) -> None:
    assert e1rm_by_exercise(conn, today) == {}


def test_returns_best_e1rm_per_exercise(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    # The seed fixture logs rpe=8.0 by default, i.e. 2 reps in reserve, so Epley
    # runs on reps+2 (see load_mechanics.effective_reps_sql). A set stopped 2
    # short of failure implies a higher 1RM than its raw rep count does.
    seed.workout(days_ago(today, 5), ex, [(90, 5)])    # eff 7 reps -> 90*1.233 = 111.0
    seed.workout(days_ago(today, 3), ex, [(100, 3)])   # eff 5 reps -> 100*1.167 = 116.7 (best)
    result = e1rm_by_exercise(conn, today)
    assert result[ex] == pytest.approx(100 * (1 + 5 / 30))


def test_excludes_warmup_sets(conn, seed, today: date) -> None:
    ex = "Squat (Barbell)"
    seed.workout(days_ago(today, 2), ex, [(200, 1)], is_warmup=True)  # would be huge
    seed.workout(days_ago(today, 2), ex, [(100, 5)], is_warmup=False)
    result = e1rm_by_exercise(conn, today)
    assert result[ex] < 130  # warmup 200kg single excluded


def test_excludes_sets_outside_window(conn, seed, today: date) -> None:
    ex = "Deadlift (Barbell)"
    seed.workout(days_ago(today, 120), ex, [(180, 3)])  # outside 90d
    seed.workout(days_ago(today, 10), ex, [(120, 5)])   # inside
    result = e1rm_by_exercise(conn, today)
    assert result[ex] < 160  # old heavy pull excluded


def test_multiple_exercises_keyed_separately(conn, seed, today: date) -> None:
    seed.workout(days_ago(today, 5), "Bench Press (Barbell)", [(90, 5)])
    seed.workout(days_ago(today, 5), "Squat (Barbell)", [(140, 5)])
    result = e1rm_by_exercise(conn, today)
    assert set(result) == {"Bench Press (Barbell)", "Squat (Barbell)"}


def test_dumbbell_e1rm_uses_logged_weight_as_per_hand(conn, seed, today: date) -> None:
    # Hevy logs the weight of ONE dumbbell, so the logged number already IS the
    # per-hand load — e1RM must NOT halve it. A 20 lb lateral raise (9.07 kg)
    # yields a per-hand e1RM of 20*1.4 lb; halving it to 10 lb/hand and
    # prescribing 7.5 lb was the ceiling-corruption bug.
    ex = "Lateral Raise (Dumbbell)"
    seed.workout(days_ago(today, 4), ex, [(9.07, 12)])  # 20 lb dumbbells, per hand
    result = e1rm_by_exercise(conn, today)
    expected_per_hand = 9.07 * (1 + 12 / 30)  # ~12.7 kg = ~28 lb, NOT halved
    assert result[ex] == pytest.approx(expected_per_hand)


def test_barbell_not_halved(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    seed.workout(days_ago(today, 4), ex, [(100, 5)])
    result = e1rm_by_exercise(conn, today)
    # Full bar load, no ÷2. Reps are 5+2 RIR (fixture logs rpe=8.0).
    assert result[ex] == pytest.approx(100 * (1 + 7 / 30))


def test_gross_outlier_set_is_trimmed(conn, seed, today: date) -> None:
    # A dense, consistent history plus one fat-fingered heavy log: the outlier
    # must not float the ceiling. Barbell so per-hand normalization is a no-op.
    ex = "Barbell Curl"
    for i in range(10):
        seed.workout(days_ago(today, 10 + i), ex, [(40, 10)])  # steady ~53kg e1RM
    seed.workout(days_ago(today, 1), ex, [(400, 1)])  # impossible fat-finger
    result = e1rm_by_exercise(conn, today)
    assert result[ex] < 100  # outlier rejected, not the ~53kg MAD-consistent max


# ── RIR-adjusted e1RM ────────────────────────────────────────────────────────
# Epley assumes the input set went to failure. Rob's don't — his best logged
# sets sit at RPE 7-8. Feeding raw reps understated e1RM, and since the day's
# load ceiling is a PERCENTAGE of e1RM, the understatement compounded into the
# prescription: a MODERATE day's 90% cap landed near 64% of what he'd just
# lifted at RPE 8. These lock the guards, all of which err downward.


def test_missing_rpe_scores_exactly_as_before(conn, seed, today: date) -> None:
    """~87% of logged history predates RPE. NULL must add nothing.

    If a missing RPE were ever read as "0 RIR credit assumed generously" — or
    worse, defaulted to some nominal RPE — every pre-2026 set would silently
    inflate the ceiling it feeds.
    """
    ex = "Bench Press (Barbell)"
    seed.workout(days_ago(today, 3), ex, [(100, 5)], rpe=None)
    assert e1rm_by_exercise(conn, today)[ex] == pytest.approx(100 * (1 + 5 / 30))


def test_rir_credit_is_capped_so_an_easy_set_cannot_extrapolate_far(
    conn, seed, today: date
) -> None:
    """RPE 5 implies 5 RIR, but credit stops at MAX_RIR_CREDIT (3).

    A set that far from failure is a weak 1RM anchor; extrapolating the full
    distance would let a deliberately light day raise the ceiling.
    """
    ex = "Squat (Barbell)"
    seed.workout(days_ago(today, 3), ex, [(100, 5)], rpe=5.0)
    # 5 + 3 (capped), not 5 + 5
    assert e1rm_by_exercise(conn, today)[ex] == pytest.approx(100 * (1 + 8 / 30))


def test_rep_cap_applies_after_the_rir_adjustment(conn, seed, today: date) -> None:
    """The 12-rep Epley cap binds on the ADJUSTED value, not before it.

    Capping first would let a 12-rep RPE-7 set score as 15 effective reps —
    deep into the range where Epley's overestimate is the known failure mode
    and the reason the cap exists at all.
    """
    ex = "Deadlift (Barbell)"
    seed.workout(days_ago(today, 3), ex, [(100, 12)], rpe=7.0)  # 12+3 -> capped to 12
    assert e1rm_by_exercise(conn, today)[ex] == pytest.approx(100 * (1 + 12 / 30))


def test_rpe_10_gets_no_credit_and_over_10_never_subtracts(conn, seed, today: date) -> None:
    """RPE 10 is failure — 0 RIR. A malformed RPE above 10 must not go negative."""
    ex = "Overhead Press (Barbell)"
    seed.workout(days_ago(today, 3), ex, [(100, 5)], rpe=10.0)
    assert e1rm_by_exercise(conn, today)[ex] == pytest.approx(100 * (1 + 5 / 30))

    ex2 = "Front Squat"
    seed.workout(days_ago(today, 3), ex2, [(100, 5)], rpe=11.0)  # nonsense input
    assert e1rm_by_exercise(conn, today)[ex2] == pytest.approx(100 * (1 + 5 / 30))
