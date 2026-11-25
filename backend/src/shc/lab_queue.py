"""Lanes, the approved queue, and the lab-screen read model (WP 2.3).

Three cadences, one live study each. Daily and weekly studies are rows in
``experiments`` (the design picks the lane); the monthly lane is the fixed-protocol
block experiment. A study can sit as ``approved`` until its lane is free; the
nightly job calls `promote_queue`, which starts the oldest approved study whose
lane is empty on the lane's boundary (any day for daily, Monday for weekly).
Nothing here registers or approves a study: Rob's yes is the ``approved`` row.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import duckdb

from shc import block_experiment, selflab

log = logging.getLogger(__name__)

#: lane -> (design, unit, boundary weekday or None for any day)
LANES: dict[str, tuple[str | None, str, int | None]] = {
    "daily": ("randomized_alternating", "a day", None),
    "weekly": ("randomized_per_session", "a session of one lift", 0),
    "monthly": (None, "a limb over 8 weeks", 0),
}
_QUEUED_LANES = ("daily", "weekly")


def lane_of(design: str) -> str | None:
    """Lane a design runs in; observational studies have none."""
    return next((k for k, (d, _, _) in LANES.items() if d == design), None)


def _day(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _active(conn: duckdb.DuckDBPyConnection, design: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT id, slug FROM experiments WHERE status = 'active' AND design = ?", [design]
    ).fetchone()
    return (str(row[0]), row[1]) if row else None


def _queue(conn: duckdb.DuckDBPyConnection, design: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, slug, hypothesis, outcome_metric FROM experiments "
        "WHERE status = 'approved' AND design = ? ORDER BY preregistered_at, slug",
        [design],
    ).fetchall()
    return [{"id": str(i), "slug": s, "hypothesis": h, "outcome_metric": m} for i, s, h, m in rows]


def promote_queue(
    conn: duckdb.DuckDBPyConnection, today: date | None = None
) -> list[dict[str, Any]]:
    """Start the next approved study in every empty lane that is at its boundary.

    The study's start date becomes ``today`` (so its arm sequence is fixed from that
    day). A candidate is skipped, and the reason returned, when its outcome is already
    being studied by an active randomized study or the answerability gate now refuses
    it; the next approved study in the lane is tried instead.

    Returns:
        One dict per decision: ``{"lane", "slug", "action": "started"|"blocked", "reason"?}``.
    """
    today = today or date.today()
    out: list[dict[str, Any]] = []
    for lane in _QUEUED_LANES:
        design, _, weekday = LANES[lane]
        assert design is not None
        if _active(conn, design) or (weekday is not None and today.weekday() != weekday):
            continue
        for cand in _queue(conn, design):
            exp = selflab.load(conn, cand["id"])
            assert exp is not None
            try:
                selflab._check_answerable(
                    conn,
                    outcome_metric=exp.outcome_metric,
                    min_effect=exp.min_effect,
                    design=exp.design,
                    slug=exp.slug,
                )
            except ValueError as exc:
                out.append(
                    {"lane": lane, "slug": exp.slug, "action": "blocked", "reason": str(exc)}
                )
                log.warning("lab queue: %s blocked in %s lane: %s", exp.slug, lane, exc)
                continue
            conn.execute(
                "UPDATE experiments SET status = 'active', started_on = ?, autolog_from = ? "
                "WHERE id = ?",
                [today.isoformat(), today.isoformat(), exp.id],
            )
            out.append({"lane": lane, "slug": exp.slug, "action": "started"})
            log.info("lab queue: started %s in the %s lane", exp.slug, lane)
            break
    return out


def _block_state(today: date) -> str:
    end = block_experiment.LAST_WEEK + timedelta(days=7)
    if today < block_experiment.PLACEBO_WEEK:
        return "not_started"
    return "running" if today < end else "closed"


def idle_notes(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> list[str]:
    """One plain line per lane with nothing running and nothing approved (for the digest)."""
    today = today or date.today()
    notes = []
    for lane in _QUEUED_LANES:
        design = LANES[lane][0]
        assert design is not None
        if not _active(conn, design) and not _queue(conn, design):
            notes.append(
                f"Lane idle: {lane}. No study is running and none is approved; "
                "a proposal here would start on the next boundary."
            )
    if _block_state(today) == "closed":
        notes.append("Lane idle: monthly. The block experiment has closed; nothing is queued.")
    return notes


def _running(conn: duckdb.DuckDBPyConnection, exp_id: str, today: date) -> dict[str, Any]:
    exp = selflab.load(conn, exp_id)
    assert exp is not None
    log_rows = conn.execute(
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE adhered), "
        "COUNT(*) FILTER (WHERE adhered = FALSE), COUNT(*) FILTER (WHERE adhered IS NULL) "
        "FROM experiment_log WHERE experiment_id = ?",
        [exp.id],
    ).fetchone()
    assert log_rows is not None
    logged, yes, no, unanswered = (int(x) for x in log_rows)
    power = selflab._power_or_none(conn, exp.id)
    assignment = next(
        (a for a in selflab.todays_assignments(conn, today) if a["id"] == exp.id), None
    )
    answer_in = power["days_to_answer"] if power else None
    return {
        "slug": exp.slug,
        "title": conn.execute("SELECT title FROM experiments WHERE id = ?", [exp.id]).fetchone()[0],  # type: ignore[index]
        "hypothesis": exp.hypothesis,
        "outcome_metric": exp.outcome_metric,
        "started_on": exp.started_on.isoformat(),
        "today": (
            {"arm": assignment["arm"], "condition": assignment["condition"]} if assignment else None
        ),
        "adherence": {
            "logged": logged,
            "followed": yes,
            "not_followed": no,
            "unanswered": unanswered,
        },
        "needed_per_arm": power["needed_per_arm"] if power else None,
        "have": power["have"] if power else None,
        "days_to_look": answer_in,
        "look_date": (today + timedelta(days=answer_in)).isoformat()
        if answer_in is not None
        else None,
    }


def _monthly(conn: duckdb.DuckDBPyConnection, today: date) -> dict[str, Any]:
    sc = block_experiment.score(conn, today)
    state = _block_state(today)
    end = block_experiment.LAST_WEEK + timedelta(days=7)
    week = today - timedelta(days=today.weekday())
    target_week = max(week, block_experiment.PLACEBO_WEEK)
    phase = block_experiment._phase(target_week)
    low = "left" if sc["high_arm"] == "right" else "right"
    if phase == "placebo":
        plan = {"left": "8 sets", "right": "8 sets", "note": "placebo week, both arms equal"}
    elif phase == "deload":
        plan = {"left": "deload", "right": "deload", "note": "deload week, excluded from scoring"}
    else:
        plan = {
            sc["high_arm"]: f"{int(block_experiment.HIGH_SETS_MIN)}+ sets",
            low: "8 sets",
            "note": "dose week",
        }
    return {
        "state": state,
        "slug": sc["slug"],
        "starts_on": block_experiment.PLACEBO_WEEK.isoformat(),
        "look_date": (end - timedelta(days=1)).isoformat(),
        "days_to_look": max(0, (end - today).days) if state != "closed" else 0,
        "days_to_start": max(0, (block_experiment.PLACEBO_WEEK - today).days),
        "verdict": sc["verdict"],
        "reason": sc["reason"],
        "week_plan": {"week": target_week.isoformat(), "phase": phase, **plan},
        "weekly": sc["weekly"],
        "delivery": sc["delivery"],
    }


def lanes(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict[str, Any]:
    """Read model for the lab screen: each lane's state, running study and queue."""
    today = today or date.today()
    out: list[dict[str, Any]] = []
    for lane, (design, unit, weekday) in LANES.items():
        entry: dict[str, Any] = {"lane": lane, "unit": unit}
        if design is None:
            entry |= {"state": "monthly", "block": _monthly(conn, today), "queue": []}
        else:
            active = _active(conn, design)
            queue = _queue(conn, design)
            entry["queue"] = queue
            entry["boundary"] = "any day" if weekday is None else "Monday"
            entry["running"] = _running(conn, active[0], today) if active else None
            entry["state"] = "running" if active else ("queued" if queue else "idle")
        out.append(entry)
    return {"today": today.isoformat(), "lanes": out, "notes": idle_notes(conn, today)}
