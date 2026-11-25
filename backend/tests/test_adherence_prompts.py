"""One-tap adherence: yes, no and unanswered days for a daily study."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from shc import adherence_prompts as ap
from shc import notify, selflab
from shc.config import settings


def _reg(conn, started: date) -> str:
    return selflab.preregister(
        conn,
        slug="bed-time",
        hypothesis="Earlier bedtime raises sleep efficiency.",
        manipulated="bedtime",
        condition_a="usual bedtime",
        condition_b="30 min earlier",
        outcome_metric="hrv_next_morning",
        min_effect=2.0,
        started_on=started,
    )


def _row(conn, exp: str, day: date):
    return conn.execute(
        "SELECT adhered, note FROM experiment_log WHERE experiment_id = ? AND day = ?",
        [exp, day.isoformat()],
    ).fetchone()


def test_evening_reserves_tomorrow_as_unanswered_and_autolog_keeps_it_null(conn) -> None:
    today = date(2026, 12, 10)
    exp = _reg(conn, today - timedelta(days=3))
    msgs = ap.evening_prompts(conn, today)
    assert len(msgs) == 1 and msgs[0].actions == []
    assert _row(conn, exp, today + timedelta(days=1)) == (None, ap.AWAITING)
    # the next night's autolog must not turn the unanswered day into an assumed yes
    selflab.autolog_randomized(conn, exp, today=today + timedelta(days=3))
    assert _row(conn, exp, today + timedelta(days=1))[0] is None


def test_yes_no_and_unanswered(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "tailscale_host", "host.example.ts.net")
    start = date(2026, 12, 1)
    exp = _reg(conn, start)
    d1, d2, d3 = date(2026, 12, 5), date(2026, 12, 6), date(2026, 12, 7)
    for d in (d1, d2, d3):
        ap.evening_prompts(conn, d - timedelta(days=1))

    morning = ap.morning_prompts(conn, d1 + timedelta(days=1))
    assert [a["label"] for a in morning[0].actions] == ["Yes", "No"]
    yes, no = morning[0].actions
    assert yes["url"] == "https://host.example.ts.net/api/experiments/bed-time/log"
    assert json.loads(yes["body"]) == {"day": d1.isoformat(), "adhered": True}
    assert json.loads(no["body"])["adhered"] is False

    # what the buttons do server side: the route calls log_day with the body
    selflab.log_day(conn, exp, d1, adhered=True)
    selflab.log_day(conn, exp, d2, adhered=False)
    assert [_row(conn, exp, d)[0] for d in (d1, d2, d3)] == [True, False, None]
    # answered days are not asked again; unanswered one still is
    assert ap.morning_prompts(conn, d1 + timedelta(days=1)) == []
    assert len(ap.morning_prompts(conn, d3 + timedelta(days=1))) == 1


def test_morning_without_tailnet_host_fails_loudly(conn, monkeypatch) -> None:
    monkeypatch.setattr(settings, "tailscale_host", None)
    _reg(conn, date(2026, 12, 1))
    ap.evening_prompts(conn, date(2026, 12, 4))
    with pytest.raises(RuntimeError):
        ap.morning_prompts(conn, date(2026, 12, 6))


def test_phone_alert_with_actions_publishes_json(monkeypatch, tmp_path, httpx_mock) -> None:
    topic = tmp_path / "t"
    topic.write_text("synthetic-topic")
    monkeypatch.setattr(notify, "NTFY_TOPIC_FILE", topic)
    httpx_mock.add_response(url="https://ntfy.sh/", status_code=200)
    acts = [{"action": "http", "label": "Yes", "url": "https://x/y"}]
    assert asyncio.run(notify.send_phone_alert("t", "m", acts)) is True
    body = json.loads(httpx_mock.get_request().content)
    assert body["topic"] == "synthetic-topic" and body["actions"] == acts


def test_prompt_jobs_are_scheduled() -> None:
    from shc.scheduler import jobs

    sched = jobs.get_scheduler()
    jobs.register_jobs(sched)
    assert "hour='20'" in str(sched.get_job("adherence_prompt_evening").trigger)
    assert "hour='8'" in str(sched.get_job("adherence_prompt_morning").trigger)
