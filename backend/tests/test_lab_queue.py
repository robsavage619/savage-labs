"""Lanes and the approved queue: promotion, one active per lane, idle notes."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import seed_outcome_history

from shc import lab_queue, selflab

LIFT = "Preacher Curl (Dumbbell)"


def _daily(conn, slug: str, *, queued: bool = False) -> str:
    seed_outcome_history(conn, "hrv_next_morning")
    return selflab.preregister(
        conn,
        slug=slug,
        hypothesis="h",
        manipulated="bedtime",
        condition_a="usual",
        condition_b="earlier",
        outcome_metric="hrv_next_morning",
        min_effect=2.0,
        started_on=date.today(),
        queued=queued,
    )


def _weekly(conn, slug: str, *, queued: bool = False) -> str:
    seed_outcome_history(conn, f"top_set_e1rm:{LIFT}")
    return selflab.preregister(
        conn,
        slug=slug,
        hypothesis="h",
        manipulated="caffeine",
        condition_a="none",
        condition_b="200mg",
        outcome_metric=f"top_set_e1rm:{LIFT}",
        min_effect=2.0,
        design="randomized_per_session",
        adherence_tag_a="nocaf",
        adherence_tag_b="caf",
        queued=queued,
    )


def _status(conn, slug: str) -> str:
    return conn.execute("SELECT status FROM experiments WHERE slug = ?", [slug]).fetchone()[0]


def test_queued_study_waits_and_a_second_active_in_the_lane_is_refused(conn) -> None:
    _daily(conn, "first")
    _daily(conn, "second", queued=True)
    assert _status(conn, "second") == "approved"
    assert [a["slug"] for a in selflab.todays_assignments(conn)] == ["first"]
    with pytest.raises(ValueError, match="one active study per lane"):
        _daily(conn, "third")


def test_promotion_waits_for_a_free_lane_then_starts_the_oldest(conn) -> None:
    _daily(conn, "first")
    _daily(conn, "second", queued=True)
    _daily(conn, "third", queued=True)
    today = date.today()
    assert lab_queue.promote_queue(conn, today) == []
    selflab.abandon(conn, "first", "ended early for the queue test")
    done = lab_queue.promote_queue(conn, today)
    assert done == [{"lane": "daily", "slug": "second", "action": "started"}]
    assert (_status(conn, "second"), _status(conn, "third")) == ("active", "approved")
    assert conn.execute(
        "SELECT started_on, autolog_from FROM experiments WHERE slug = 'second'"
    ).fetchone() == (today, today)
    assert lab_queue.promote_queue(conn, today) == []


def test_weekly_lane_starts_only_on_a_monday(conn) -> None:
    _weekly(conn, "caf", queued=True)
    monday = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    assert lab_queue.promote_queue(conn, monday + timedelta(days=2)) == []
    assert _status(conn, "caf") == "approved"
    assert lab_queue.promote_queue(conn, monday)[0]["action"] == "started"
    assert (
        conn.execute("SELECT started_on FROM experiments WHERE slug='caf'").fetchone()[0] == monday
    )


def test_empty_queue_raises_a_lane_idle_note(conn) -> None:
    notes = lab_queue.idle_notes(conn, date(2026, 11, 25))
    assert [n.split(".")[0] for n in notes] == ["Lane idle: daily", "Lane idle: weekly"]
    _daily(conn, "d", queued=True)
    assert [n.split(".")[0] for n in lab_queue.idle_notes(conn, date(2026, 11, 25))] == [
        "Lane idle: weekly"
    ]
    assert lab_queue.idle_notes(conn, date(2027, 2, 1))[-1].startswith("Lane idle: monthly")


def test_lanes_view_reports_each_state_including_block_not_started(conn) -> None:
    _daily(conn, "run")
    _daily(conn, "wait", queued=True)
    view = lab_queue.lanes(conn, date(2026, 11, 25))
    by = {lane["lane"]: lane for lane in view["lanes"]}
    assert by["daily"]["state"] == "running" and by["daily"]["running"]["slug"] == "run"
    assert [q["slug"] for q in by["daily"]["queue"]] == ["wait"]
    assert by["weekly"]["state"] == "idle"
    block = by["monthly"]["block"]
    assert block["state"] == "not_started" and block["days_to_start"] == 5
    assert block["verdict"] == "pending" and block["week_plan"]["phase"] == "placebo"
