"""exercise_muscle_map keeps one primary per exercise; a second one is dropped silently."""

from __future__ import annotations

from datetime import date, timedelta

from shc.training.volume import weekly_muscle_volume


def test_no_exercise_has_two_primary_muscles(conn) -> None:
    rows = conn.execute(
        """
        SELECT exercise_name FROM exercise_muscle
        GROUP BY 1 HAVING count(*) FILTER (WHERE role = 'primary') > 1
        """
    ).fetchall()
    assert rows == []


def test_stiff_legged_deadlift_credits_hamstrings(conn, seed) -> None:
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES ('Smith Machine Stiff-Legged Deadlift', 'hamstrings', 'primary', 1.0) "
        "ON CONFLICT DO NOTHING"
    )
    seed.workout(date.today(), "Smith Machine Stiff-Legged Deadlift", [(100.0, 10)] * 2, rpe=8.0)
    start = date.today() - timedelta(days=date.today().weekday())
    assert weekly_muscle_volume(conn, start).get("hamstrings", 0) >= 2.0
