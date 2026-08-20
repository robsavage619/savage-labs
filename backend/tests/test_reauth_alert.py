"""The alert that turns a dead OAuth token from a silent failure into a loud one.

`oauth_state.needs_reauth` was written correctly for its whole life and read by
nobody unattended, so on 2026-08-17 a dead WHOOP token went unnoticed for 2.5
days. These tests pin the state machine that closes that gap: alert on the
transition into broken, re-nag on a cadence while it stays broken, go quiet
otherwise, and re-arm once the source reconnects.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from shc.scheduler import jobs


@pytest.fixture
def alert_env(conn: duckdb.DuckDBPyConnection, monkeypatch):
    """Run _check_reauth_alerts against the in-memory DB, capturing alerts."""
    sent: list[dict[str, str]] = []

    @asynccontextmanager
    async def _write_ctx():
        yield conn

    async def _send(title: str, subtitle: str, message: str) -> bool:
        sent.append({"title": title, "subtitle": subtitle, "message": message})
        return True

    monkeypatch.setattr("shc.db.schema.write_ctx", _write_ctx)
    monkeypatch.setattr("shc.notify.send_desktop_alert", _send)

    def _run() -> list[dict[str, str]]:
        sent.clear()
        asyncio.run(jobs._check_reauth_alerts())
        return sent

    return conn, _run


def _set_state(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    *,
    needs_reauth: bool,
    last_sync_at: datetime | None = None,
    alerted_at: datetime | None = None,
) -> None:
    conn.execute("DELETE FROM oauth_state WHERE source = ?", [source])
    conn.execute(
        "INSERT INTO oauth_state (source, last_sync_at, needs_reauth, reauth_alerted_at) "
        "VALUES (?, ?, ?, ?)",
        [source, last_sync_at, needs_reauth, alerted_at],
    )


def _alerted_at(conn: duckdb.DuckDBPyConnection, source: str) -> datetime | None:
    return conn.execute(
        "SELECT reauth_alerted_at FROM oauth_state WHERE source = ?", [source]
    ).fetchone()[0]


def test_alerts_on_transition_into_broken(alert_env):
    conn, run = alert_env
    _set_state(conn, "whoop", needs_reauth=True, last_sync_at=datetime.now(UTC))

    sent = run()

    assert len(sent) == 1
    assert "WHOOP" in sent[0]["title"]
    # The reauth URL is the whole point of the alert, and it is the one people
    # get wrong: /auth, never /api.
    assert "http://127.0.0.1:8000/auth/whoop/login" in sent[0]["message"]
    assert _alerted_at(conn, "whoop") is not None


def test_healthy_source_never_alerts(alert_env):
    conn, run = alert_env
    _set_state(conn, "whoop", needs_reauth=False, last_sync_at=datetime.now(UTC))

    assert run() == []


def test_does_not_realert_inside_the_renag_window(alert_env):
    """The job polls every 30 min; without this it would alert 48x/day."""
    conn, run = alert_env
    recent = datetime.now(UTC) - timedelta(hours=jobs.REAUTH_RENAG_HOURS - 1)
    _set_state(conn, "whoop", needs_reauth=True, alerted_at=recent)

    assert run() == []
    assert _alerted_at(conn, "whoop") == recent  # untouched


def test_renags_once_past_the_window(alert_env):
    """A banner missed while it was on screen is unrecoverable — remind him."""
    conn, run = alert_env
    stale = datetime.now(UTC) - timedelta(hours=jobs.REAUTH_RENAG_HOURS + 1)
    _set_state(conn, "whoop", needs_reauth=True, alerted_at=stale)

    assert len(run()) == 1
    assert _alerted_at(conn, "whoop") > stale


def test_reconnecting_rearms_for_the_next_break(alert_env):
    """Break -> fix -> break inside one window must still alert the second time."""
    conn, run = alert_env
    just_now = datetime.now(UTC) - timedelta(minutes=5)
    _set_state(conn, "whoop", needs_reauth=False, alerted_at=just_now)

    assert run() == []
    assert _alerted_at(conn, "whoop") is None  # re-armed

    _set_state(conn, "whoop", needs_reauth=True, alerted_at=None)
    assert len(run()) == 1


def test_reports_staleness_in_days_once_past_a_day(alert_env):
    """The 2026-08-17 outage ran 2.5 days; the alert must convey that scale."""
    conn, run = alert_env
    _set_state(
        conn,
        "whoop",
        needs_reauth=True,
        last_sync_at=datetime.now(UTC) - timedelta(days=2, hours=12),
    )

    assert "2.5 days stale" in run()[0]["subtitle"]


def test_reports_staleness_in_hours_when_fresh(alert_env):
    conn, run = alert_env
    _set_state(
        conn, "whoop", needs_reauth=True, last_sync_at=datetime.now(UTC) - timedelta(hours=3)
    )

    assert "3h stale" in run()[0]["subtitle"]


def test_source_without_a_reauth_url_still_alerts(alert_env):
    """DUPR has no OAuth redirect — it must not be silently skipped."""
    conn, run = alert_env
    _set_state(conn, "dupr", needs_reauth=True)

    sent = run()

    assert len(sent) == 1
    assert "DUPR" in sent[0]["title"]
    assert "http" not in sent[0]["message"]


def test_undelivered_alert_is_still_stamped(conn, monkeypatch):
    """A failing notifier must not re-fire every 30 min forever."""

    @asynccontextmanager
    async def _write_ctx():
        yield conn

    async def _fail(title: str, subtitle: str, message: str) -> bool:
        return False

    monkeypatch.setattr("shc.db.schema.write_ctx", _write_ctx)
    monkeypatch.setattr("shc.notify.send_desktop_alert", _fail)
    _set_state(conn, "whoop", needs_reauth=True)

    asyncio.run(jobs._check_reauth_alerts())

    assert _alerted_at(conn, "whoop") is not None
