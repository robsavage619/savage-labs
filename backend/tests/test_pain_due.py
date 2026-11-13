"""The pain question follows the last lifting session until it is answered, even with 'none'."""

from __future__ import annotations

from datetime import date, datetime

from shc.api.routers.dashboard import pain_due

TODAY = date(2026, 11, 13)


def _hevy(conn, day: date) -> None:
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, content_hash) VALUES (?, 'hevy', ?, ?)",
        [f"w{day}", datetime.combine(day, datetime.min.time()), f"h{day}"],
    )


def test_due_after_session_until_answered(conn) -> None:
    assert pain_due(conn, TODAY)["due"] is False
    _hevy(conn, date(2026, 11, 12))
    assert pain_due(conn, TODAY) == {"due": True, "date": "2026-11-12"}
    conn.execute(
        "INSERT INTO daily_checkin (date, joint_pain_by_region_json) VALUES ('2026-11-12', '{}')"
    )
    assert pain_due(conn, TODAY)["due"] is False


def test_older_sessions_are_not_asked_about(conn) -> None:
    _hevy(conn, date(2026, 11, 10))
    assert pain_due(conn, TODAY)["due"] is False
