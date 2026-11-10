from __future__ import annotations

import asyncio
from datetime import date, timedelta

import duckdb

from shc.api.routers import dashboard


def _seed(conn: duckdb.DuckDBPyConnection) -> None:
    start = date(2025, 1, 1)
    for i in range(30):
        d = start + timedelta(days=i)
        conn.execute(
            "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES (?, 'whoop', ?, 60, ?, 50, ?)",
            [f"r{i}", d, 150.0 if i == 0 else 100.0 + (i % 2) * 10, f"h{i}"],
        )
        # One yes-day carrying a huge HRV: the shape that put +23 ms on top of the chart.
        conn.execute(
            "INSERT INTO whoop_journal (id, cycle_start, date, question, answered_yes, content_hash) "
            "VALUES (?, ?, ?, 'Thin?', ?, 'x')",
            [f"t{i}", d, d, i == 0],
        )
        # Balanced question, 15 yes / 15 no, yes-days 10 ms higher.
        conn.execute(
            "INSERT INTO whoop_journal (id, cycle_start, date, question, answered_yes, content_hash) "
            "VALUES (?, ?, ?, 'Balanced?', ?, 'x')",
            [f"b{i}", d, d, i % 2 == 1],
        )


def test_thin_question_gets_no_delta_and_balanced_one_leads(conn, monkeypatch) -> None:
    _seed(conn)
    monkeypatch.setattr(dashboard, "get_read_conn", lambda: conn.cursor())
    rows = asyncio.run(dashboard.insights_correlations())
    by_q = {r["question"]: r for r in rows}

    thin = by_q["Thin?"]
    assert (thin["n_yes"], thin["n_no"]) == (1, 29)
    assert thin["hrv_delta"] is None

    bal = by_q["Balanced?"]
    assert (bal["n_yes"], bal["n_no"]) == (15, 15)
    assert bal["hrv_delta"] is not None
    assert bal["hrv_ci_low"] < bal["hrv_delta"] < bal["hrv_ci_high"]
    assert rows[0]["question"] == "Balanced?"
