"""Tape history returns every manual reading in cm, oldest first, named by site."""

from __future__ import annotations

from datetime import datetime

from shc.api.routers.dashboard import tape_history


def test_tape_history_lists_every_manual_reading(conn) -> None:
    rows = [
        ("manual", "waist_circumference_cm", datetime(2026, 12, 1), 109.22),
        ("manual", "thigh_circumference_cm", datetime(2026, 11, 3), 68.58),
        ("manual", "waist_circumference_cm", datetime(2026, 11, 3), 110.49),
        ("apple", "waist_circumference_cm", datetime(2026, 11, 4), 99.0),  # not a tape reading
    ]
    for source, metric, ts, cm in rows:
        conn.execute(
            "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
            "VALUES (?, ?, ?, ?, 'cm', ?, ?)",
            [source, metric, ts, cm, f"{source}{metric}{ts}", f"{source}{metric}{ts}"],
        )

    assert tape_history(conn) == [
        {"date": "2026-11-03", "site": "thigh", "cm": 68.6},
        {"date": "2026-11-03", "site": "waist", "cm": 110.5},
        {"date": "2026-12-01", "site": "waist", "cm": 109.2},
    ]
