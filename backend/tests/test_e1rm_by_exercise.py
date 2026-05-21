from __future__ import annotations

from datetime import date, timedelta

from shc.ai.workout_planner import e1rm_by_exercise


def days_ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


def test_empty_when_no_data(conn, today: date) -> None:
    assert e1rm_by_exercise(conn, today) == {}


def test_returns_best_e1rm_per_exercise(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    seed.workout(days_ago(today, 5), ex, [(90, 5)])    # 90*1.167 = 105
    seed.workout(days_ago(today, 3), ex, [(100, 3)])   # 100*1.10 = 110 (best)
    result = e1rm_by_exercise(conn, today)
    assert result[ex] == round(100 * (1 + 3 / 30), 4) or abs(result[ex] - 110.0) < 0.01


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
