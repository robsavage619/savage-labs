"""Guards for Foster monotony and strain.

Monotony is a ratio whose denominator is a standard deviation, which makes it
easy to compute confidently and wrongly: a week with one session has a large SD
driven entirely by rest days, and reports as maximally VARIED when the truth is
that there is not enough training to say anything.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from shc.stats.training_monotony import monotony_series

_MON = date.today() - timedelta(days=date.today().weekday())


def _day(conn, day: date, sets: int, rpe: float = 8.0, weight: float = 50.0) -> None:
    wid = f"w{day}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) VALUES (?,'hevy',?,'strength',?)",
        [wid, datetime.combine(day, datetime.min.time()), f"h{day}"],
    )
    for i in range(sets):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, rpe, is_warmup, content_hash) "
            "VALUES (?,?,?,'Bench Press',?,10,?,FALSE,?)",
            [f"{wid}s{i}", wid, i, weight, rpe, f"c{wid}{i}"],
        )


def test_identical_daily_training_scores_high_monotony(conn):
    """Seven identical days is the definition of monotonous."""
    for wk in range(4):
        for d in range(7):
            _day(conn, _MON - timedelta(weeks=wk + 1) + timedelta(days=d), 5)
    out = monotony_series(conn)
    assert out["monotony_max"] > 5.0
    assert out["verdict"] == "monotonous weeks present"
    assert out["weeks_above_heuristic"] > 0
    # SD is exactly zero here. The week must be REPORTED as maximally
    # monotonous, not silently dropped for dividing by zero.
    assert all(w["perfectly_uniform"] for w in out["weeks"])


def test_varied_training_scores_low_monotony(conn):
    for wk in range(4):
        base = _MON - timedelta(weeks=wk + 1)
        _day(conn, base, 10)
        _day(conn, base + timedelta(days=2), 3)
        _day(conn, base + timedelta(days=4), 8)
    out = monotony_series(conn)
    assert out["monotony_max"] < 2.0
    assert out["verdict"] == "varied"


def test_a_single_session_week_is_excluded_not_scored(conn):
    """One session + six zeros has a big SD. That is rest, not variety."""
    for wk in range(4):
        _day(conn, _MON - timedelta(weeks=wk + 1), 5)
    out = monotony_series(conn)
    assert out["weeks"] == []
    assert out["verdict"] == "insufficient"


def test_strain_is_load_times_monotony(conn):
    for wk in range(3):
        base = _MON - timedelta(weeks=wk + 1)
        _day(conn, base, 6)
        _day(conn, base + timedelta(days=3), 4)
    out = monotony_series(conn)
    for w in out["weeks"]:
        # Compared loosely: the payload rounds monotony to 2dp and load to 1dp,
        # so the product of the rounded values is not the rounded product.
        assert w["strain"] == pytest.approx(w["load"] * w["monotony"], rel=0.02)


def test_attribution_names_foster_1998_not_2001(conn):
    """The 2001 paper is session-RPE. Monotony/strain is 1998. Do not blend them."""
    for wk in range(3):
        base = _MON - timedelta(weeks=wk + 1)
        _day(conn, base, 6)
        _day(conn, base + timedelta(days=3), 4)
    a = monotony_series(conn)["attribution"]
    assert "Foster 1998" in a
    assert "10.1097/00005768-199807000-00023" in a
    assert "heuristic" in a  # the 2.0 line must not be sold as Foster's


def test_no_data_is_reported_not_faked(conn):
    assert monotony_series(conn)["verdict"] == "no data"
