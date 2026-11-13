"""Quarterly pickleball HR: medians per quarter, thin quarters dropped, other sports ignored."""

from __future__ import annotations

from datetime import datetime, timedelta

from shc.stats.pickleball import hr_cost


def _session(conn, i: int, start: datetime, avg_hr: int, sport: str = "pickleball") -> None:
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, ended_at, avg_hr, max_hr, kcal, "
        "sport_name, content_hash) VALUES (?, 'whoop', ?, ?, ?, ?, 600, ?, ?)",
        [f"w{i}", start, start + timedelta(minutes=60), avg_hr, avg_hr + 40, sport, f"h{i}"],
    )


def test_quarters_need_eight_sessions_and_take_medians(conn) -> None:
    for i in range(8):
        _session(conn, i, datetime(2025, 4, 1 + i), 130 + i)
    for i in range(7):
        _session(conn, 100 + i, datetime(2025, 7, 1 + i), 110)
    _session(conn, 200, datetime(2025, 4, 20), 180, sport="yoga")
    out = hr_cost(conn)
    assert [q["quarter"] for q in out] == ["2025 Q2"]
    assert out[0]["sessions"] == 8
    assert out[0]["avg_hr"] == 134  # median of 130..137 is 133.5, rounds to even
    assert out[0]["kcal_per_min"] == 10.0
