"""The weekly re-test reminder: who is named, and that no value leaks."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import duckdb
import pytest

from shc.scheduler import jobs

TODAY = date.today()
APOB = "ApoB (artery-clogging particle count)"
ALT = "ALT (liver enzyme)"


@pytest.fixture
def phone(monkeypatch, conn: duckdb.DuckDBPyConnection) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def _send(title: str, message: str) -> bool:
        sent.append({"title": title, "message": message})
        return True

    class _Shared:
        def execute(self, *a, **k):
            return conn.execute(*a, **k)

        def close(self) -> None:
            pass

    monkeypatch.setattr("shc.notify.send_phone_alert", _send)
    monkeypatch.setattr("shc.db.schema.get_read_conn", lambda: _Shared())
    return sent


def _lab(conn: duckdb.DuckDBPyConnection, name: str, value: float, days_ago: int) -> None:
    when = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    conn.execute(
        "INSERT INTO labs (id, name, value, unit, collected_at) VALUES (?, ?, ?, 'u', ?)",
        [f"{name}-{days_ago}-{value}", name, value, when],
    )


def test_stale_marker_is_named_without_its_value(conn, phone) -> None:
    _lab(conn, "ApoB", 41.7, 200)
    asyncio.run(jobs._retest_reminder())
    assert len(phone) == 1
    assert APOB in phone[0]["message"]
    assert "41.7" not in phone[0]["message"] and "41" not in phone[0]["message"]


def test_drifting_marker_is_named_without_values(conn, phone) -> None:
    for value, ago in ((24, 60), (26, 30), (28, 1)):
        _lab(conn, "ALT", value, ago)
    asyncio.run(jobs._retest_reminder())
    msg = phone[0]["message"]
    assert ALT in msg
    assert not any(v in msg for v in ("24", "26", "28", "30 U/L"))


def test_on_target_sends_nothing(conn, phone) -> None:
    _lab(conn, "ApoB", 40, 5)
    for ago in (60, 30, 1):
        _lab(conn, "ALT", 20, ago)
    asyncio.run(jobs._retest_reminder())
    assert phone == []


def test_one_alert_lists_every_due_marker(conn, phone) -> None:
    _lab(conn, "ApoB", 40, 200)
    _lab(conn, "ALT", 20, 200)
    asyncio.run(jobs._retest_reminder())
    assert len(phone) == 1
    assert APOB in phone[0]["message"] and ALT in phone[0]["message"]


def test_the_job_runs_weekly() -> None:
    sched = jobs.get_scheduler()
    jobs.register_jobs(sched)
    job = sched.get_job("retest_reminder")
    assert job is not None
    trigger = str(job.trigger)
    assert "day_of_week='mon'" in trigger and "hour='8'" in trigger
