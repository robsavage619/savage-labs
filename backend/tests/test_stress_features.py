from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import duckdb

from shc import research

T0 = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
DAY = date(2026, 1, 5)


def _stress(
    conn: duckdb.DuckDBPyConnection, start: datetime, minutes: int, value: float, level: str
) -> None:
    conn.executemany(
        "INSERT INTO whoop_stress_timeline (date, sampled_at, value, level) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (date, sampled_at) DO UPDATE SET value = EXCLUDED.value, level = EXCLUDED.level",
        [(DAY, start + timedelta(minutes=m), value, level) for m in range(minutes)],
    )


def test_high_stress_minutes_skip_workouts_and_gap_days(conn: duckdb.DuckDBPyConnection) -> None:
    _stress(conn, T0, 1000, 1.0, "LOW")
    _stress(conn, T0 + timedelta(minutes=100), 200, 2.5, "HIGH")  # 200 high minutes
    # the workout and its 30-minute tail hide the first 50 of them
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, ended_at, content_hash) VALUES ('w','whoop',?,?,'h')",
        [T0 + timedelta(minutes=60), T0 + timedelta(minutes=120)],
    )
    assert research.series(conn, "stress_high_min") == {DAY: 150.0}

    conn.execute(
        "DELETE FROM whoop_stress_timeline WHERE sampled_at >= ?", [T0 + timedelta(minutes=800)]
    )
    assert research.series(conn, "stress_high_min") == {}  # 800 samples: a partial day


def test_presleep_stress_is_the_two_hours_before_onset(conn: duckdb.DuckDBPyConnection) -> None:
    onset = T0 + timedelta(hours=16)
    _stress(conn, onset - timedelta(hours=3), 60, 0.0, "LOW")  # outside the window
    _stress(conn, onset - timedelta(hours=2), 120, 2.0, "MED")
    conn.execute(
        "INSERT INTO sleep (id, source, night_date, ts_in, ts_out, content_hash, is_nap) "
        "VALUES ('s','whoop',?,?,?,'h',FALSE)",
        [DAY + timedelta(days=1), onset, onset + timedelta(hours=8)],
    )
    assert research.series(conn, "presleep_stress") == {DAY + timedelta(days=1): 2.0}


def test_away_night_is_relative_to_the_usual_place(conn: duckdb.DuckDBPyConnection) -> None:
    for i in range(1, 6):
        night = T0 + timedelta(days=i, hours=16)
        conn.execute(
            "INSERT INTO sleep (id, source, night_date, ts_in, ts_out, content_hash, is_nap) "
            "VALUES (?,'whoop',?,?,?,'h',FALSE)",
            [f"s{i}", DAY + timedelta(days=i + 1), night, night + timedelta(hours=8)],
        )
        place = 2 if i == 4 else 1
        conn.execute(
            "INSERT INTO place_stays VALUES (?, ?, ?)",
            [night - timedelta(hours=2), night + timedelta(hours=9), place],
        )
    away = research.series(conn, "away_night")
    assert [away[DAY + timedelta(days=i + 1)] for i in range(1, 6)] == [0.0, 0.0, 0.0, 1.0, 0.0]
