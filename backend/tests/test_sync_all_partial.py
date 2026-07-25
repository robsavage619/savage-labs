"""Regression guard for the 2026-07-25 silent fail-open.

`POST /api/sync/all` returned `whoop: {ok: true}` while the WHOOP workout
endpoint had failed (`-1`), and the accompanying `freshness` block reported
`whoop_stale: false` off the sync attempt rather than off what persisted. The
daily brief then served two-day-old recovery as current and fired the illness
gate. Both halves are covered here.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from shc.api.routers import report
from shc.metrics import RecoveryMetrics, SleepMetrics, TrainingLoadMetrics, _freshness

# The exact detail map WHOOP returned on 2026-07-25.
INCIDENT_DETAIL = {
    "recovery": 876,
    "sleep": 968,
    "workout": -1,
    "cycle": 900,
    "body_measurement": 1,
    "user_profile": 1,
}


def _add_recovery(conn, day: date, *, score: float = 71.0, hrv: float = 136.6) -> None:
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) "
        "VALUES ($id, 'whoop', $d, $score, $hrv, 45, $id)",
        {"id": str(uuid.uuid4()), "d": day.isoformat(), "score": score, "hrv": hrv},
    )


# ── negative counts are failures, not successes ──────────────────────────────


def test_failed_endpoints_flags_negative_counts() -> None:
    assert report.failed_endpoints(INCIDENT_DETAIL) == ["workout"]


def test_failed_endpoints_empty_on_clean_sync() -> None:
    assert report.failed_endpoints({**INCIDENT_DETAIL, "workout": 784}) == []


def test_failed_endpoints_ignores_non_dict_detail() -> None:
    assert report.failed_endpoints(None) == []
    assert report.failed_endpoints(3.457) == []


@pytest.fixture
def patched_sync(conn, monkeypatch):
    """Wire sync_all's sources and read connection to the in-memory test DB."""

    def _apply(whoop_detail: object) -> None:
        async def _whoop() -> object:
            return whoop_detail

        async def _hevy() -> dict:
            return {"workouts": 0}

        async def _dupr() -> dict:
            return {"rating": 3.457}

        monkeypatch.setattr(report.whoop, "sync_all", _whoop)
        monkeypatch.setattr(report.hevy, "sync_workouts", _hevy)
        monkeypatch.setattr(report.dupr, "sync_rating", _dupr)
        monkeypatch.setattr(report, "get_read_conn", lambda: conn)

    return _apply


async def test_partial_endpoint_failure_is_not_ok(patched_sync) -> None:
    patched_sync(INCIDENT_DETAIL)
    out = await report.sync_all()
    whoop_result = out["results"]["whoop"]
    assert whoop_result["ok"] is False
    assert whoop_result["partial"] is True
    assert whoop_result["failed_endpoints"] == ["workout"]
    assert whoop_result["detail"] == INCIDENT_DETAIL
    # Sources that genuinely succeeded stay clean.
    assert out["results"]["hevy"]["ok"] is True
    assert out["results"]["dupr"]["ok"] is True


async def test_clean_sync_still_reports_ok(patched_sync) -> None:
    patched_sync({**INCIDENT_DETAIL, "workout": 784})
    out = await report.sync_all()
    assert out["results"]["whoop"] == {"ok": True, "detail": {**INCIDENT_DETAIL, "workout": 784}}


async def test_partial_failure_surfaces_a_freshness_gap(patched_sync) -> None:
    patched_sync(INCIDENT_DETAIL)
    out = await report.sync_all()
    assert any("PARTIAL" in g and "workout" in g for g in out["freshness"]["gaps"])


# ── freshness must describe the DB, not the sync attempt ─────────────────────


async def test_partial_failure_must_not_report_whoop_stale_false(conn, patched_sync) -> None:
    """The headline regression: a partial sync leaves stale rows behind.

    Newest persisted recovery is 3 days old, so the sync completing (with the
    workout endpoint failed) must not make `freshness` claim the data is fresh.
    """
    _add_recovery(conn, date.today() - timedelta(days=3))
    patched_sync(INCIDENT_DETAIL)
    out = await report.sync_all()
    assert out["results"]["whoop"]["ok"] is False
    assert out["freshness"]["whoop_age_days"] == 3
    assert out["freshness"]["whoop_stale"] is True
    assert any("WHOOP" in g and "stale" in g for g in out["freshness"]["gaps"])


def test_whoop_age_comes_from_db_not_the_passed_row(conn) -> None:
    """A `score_date` claiming today cannot override an actually-stale table."""
    _add_recovery(conn, date.today() - timedelta(days=3))
    rec = RecoveryMetrics(score_date=date.today().isoformat())
    f = _freshness(conn, date.today(), rec, SleepMetrics(), TrainingLoadMetrics())
    assert f.whoop_age_days == 3
    assert f.whoop_stale is True


def test_future_dated_recovery_row_cannot_fake_freshness(conn) -> None:
    """A timezone roll-forward must not mask the missing current row."""
    _add_recovery(conn, date.today() - timedelta(days=4))
    _add_recovery(conn, date.today() + timedelta(days=1))
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), TrainingLoadMetrics())
    assert f.whoop_age_days == 4
    assert f.whoop_stale is True
