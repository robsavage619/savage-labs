"""Tape history returns every manual reading per site in inches, oldest first."""

from __future__ import annotations

from datetime import datetime

from shc.api.routers.dashboard import tape_history


def test_tape_history_groups_manual_readings_by_site(conn) -> None:
    rows = [
        ("manual", "waist_circumference_cm", datetime(2026, 12, 1), 101.6),
        ("manual", "hip_circumference_cm", datetime(2026, 11, 3), 114.3),
        ("manual", "waist_circumference_cm", datetime(2026, 11, 3), 102.87),
        ("apple", "waist_circumference_cm", datetime(2026, 11, 4), 99.0),  # not a tape reading
    ]
    for source, metric, ts, cm in rows:
        conn.execute(
            "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
            "VALUES (?, ?, ?, ?, 'cm', ?, ?)",
            [source, metric, ts, cm, f"{source}{metric}{ts}", f"{source}{metric}{ts}"],
        )

    assert tape_history(conn) == {
        "hip_in": [{"date": "2026-11-03", "inches": 45.0}],
        "waist_in": [
            {"date": "2026-11-03", "inches": 40.5},
            {"date": "2026-12-01", "inches": 40.0},
        ],
    }
