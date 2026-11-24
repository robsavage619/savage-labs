"""The nightly reconcile job, its phone alert, and the cached /research/features."""

from __future__ import annotations

import asyncio

import pytest

from shc import notify
from shc.scheduler import jobs
from shc.training.reconcile import Finding


@pytest.fixture
def phone(monkeypatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def _send(title: str, message: str) -> bool:
        sent.append({"title": title, "message": message})
        return True

    monkeypatch.setattr("shc.notify.send_phone_alert", _send)
    return sent


def _findings(monkeypatch, findings: list[Finding]) -> None:
    class _Conn:
        def close(self) -> None:
            pass

    monkeypatch.setattr("shc.db.schema.get_read_conn", lambda: _Conn())
    monkeypatch.setattr("shc.training.reconcile.run_all", lambda _conn: findings)


def test_a_failed_check_alerts_the_phone_with_its_name_only(monkeypatch, phone) -> None:
    _findings(
        monkeypatch, [Finding("a", True, "fine"), Finding("e1rm parity", False, "3 days off")]
    )
    asyncio.run(jobs._reconcile_check())
    assert len(phone) == 1
    assert "1 of 2 checks failed: e1rm parity" in phone[0]["message"]
    assert "3 days off" not in phone[0]["message"]


def test_a_clean_run_sends_nothing(monkeypatch, phone) -> None:
    _findings(monkeypatch, [Finding("a", True, "fine"), Finding("b", True, "fine")])
    asyncio.run(jobs._reconcile_check())
    assert phone == []


def test_the_job_is_scheduled_after_the_research_run() -> None:
    sched = jobs.get_scheduler()
    jobs.register_jobs(sched)
    trigger = str(sched.get_job("reconcile_check").trigger)
    assert "hour='5'" in trigger and "minute='0'" in trigger


def test_phone_alert_without_a_topic_file_sends_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(notify, "NTFY_TOPIC_FILE", tmp_path / "missing")
    assert asyncio.run(notify.send_phone_alert("t", "m")) is False


def test_phone_alert_posts_to_the_topic(monkeypatch, tmp_path, httpx_mock) -> None:
    topic = tmp_path / "ntfy-topic"
    topic.write_text("synthetic-topic\n")
    monkeypatch.setattr(notify, "NTFY_TOPIC_FILE", topic)
    httpx_mock.add_response(url="https://ntfy.sh/synthetic-topic", status_code=200)
    assert asyncio.run(notify.send_phone_alert("SHC reconcile failed", "1 of 7")) is True
    req = httpx_mock.get_request()
    assert req.headers["Title"] == "SHC reconcile failed" and req.content == b"1 of 7"


def test_phone_alert_never_raises_on_a_server_error(monkeypatch, tmp_path, httpx_mock) -> None:
    topic = tmp_path / "ntfy-topic"
    topic.write_text("synthetic-topic")
    monkeypatch.setattr(notify, "NTFY_TOPIC_FILE", topic)
    httpx_mock.add_response(url="https://ntfy.sh/synthetic-topic", status_code=500)
    assert asyncio.run(notify.send_phone_alert("t", "m")) is False


def test_features_are_computed_once_per_window(monkeypatch) -> None:
    from shc.api.routers import research as router

    calls: list[int] = []
    monkeypatch.setattr(router, "_features_cache", None)
    monkeypatch.setattr(router, "_read", lambda fn, *a: calls.append(1) or [{"name": "x"}])
    clock = [1000.0]
    monkeypatch.setattr(router.time, "monotonic", lambda: clock[0])
    assert router.features() == [{"name": "x"}]
    clock[0] += 60
    router.features()
    assert len(calls) == 1
    clock[0] += router._FEATURES_TTL_S
    router.features()
    assert len(calls) == 2
