"""One-tap adherence for daily (alternating) studies.

Evening: tell the phone tomorrow's assignment and reserve tomorrow's log row with
``adhered = NULL``. Morning: for yesterday's still-unanswered row, send a Yes/No
notification whose buttons POST to ``/api/experiments/{slug}/log``. A day nobody
answers stays NULL, which the scorer excludes; ``autolog_randomized`` never
overwrites an existing row, so reserving the row is what opts a day out of
intention-to-treat. This records adherence only, never sets (Hevy logs sets).

Messages carry study names and protocol conditions, never health values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from shc import selflab
from shc.config import settings

log = logging.getLogger(__name__)

AWAITING = "prompt: awaiting tap"


@dataclass(frozen=True)
class Prompt:
    title: str
    message: str
    actions: list[dict] = field(default_factory=list)


def _active_daily(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str, str, date]]:
    rows = conn.execute(
        "SELECT id, slug, condition_a, condition_b, started_on FROM experiments "
        "WHERE status = 'active' AND design = 'randomized_alternating'"
    ).fetchall()
    return [
        (str(i), s, a, b, d if isinstance(d, date) else date.fromisoformat(str(d)))
        for i, s, a, b, d in rows
    ]


def evening_prompts(conn: duckdb.DuckDBPyConnection, today: date) -> list[Prompt]:
    """Tomorrow's assignment per active daily study; reserves tomorrow's NULL row."""
    tomorrow = today + timedelta(days=1)
    out: list[Prompt] = []
    for exp_id, slug, cond_a, cond_b, started in _active_daily(conn):
        if tomorrow < started:
            continue
        arm = selflab.arm_for_day(slug, started, tomorrow)
        conn.execute(
            "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, note) "
            "VALUES (?, ?, ?, NULL, ?) ON CONFLICT (experiment_id, day) DO NOTHING",
            [exp_id, tomorrow.isoformat(), arm, AWAITING],
        )
        cond = cond_a if arm == "A" else cond_b
        out.append(Prompt(f"Tomorrow: {slug}", f"Assignment for {tomorrow:%a %b %d}: {cond}"))
    return out


def _tap(label: str, url: str, day: date, adhered: bool) -> dict:
    return {
        "action": "http",
        "label": label,
        "url": url,
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"day": day.isoformat(), "adhered": adhered}),
        "clear": True,
    }


def morning_prompts(conn: duckdb.DuckDBPyConnection, today: date) -> list[Prompt]:
    """A Yes/No prompt per daily study whose row for yesterday is still unanswered.

    Raises:
        RuntimeError: if prompts are due but no tailnet host is configured, since
            buttons without a reachable URL would be a silent dead end.
    """
    yesterday = today - timedelta(days=1)
    due: list[tuple[str, str]] = []
    for exp_id, slug, cond_a, cond_b, _ in _active_daily(conn):
        row = conn.execute(
            "SELECT assigned_arm FROM experiment_log WHERE experiment_id = ? AND day = ? "
            "AND adhered IS NULL AND note = ?",
            [exp_id, yesterday.isoformat(), AWAITING],
        ).fetchone()
        if row:
            due.append((slug, cond_a if row[0] == "A" else cond_b))
    if not due:
        return []
    if not settings.tailscale_host:
        raise RuntimeError("TAILSCALE_HOST is not set; cannot build tap-to-log URLs")
    base = f"https://{settings.tailscale_host}/api/experiments"
    return [
        Prompt(
            f"Did you follow it? {slug}",
            f"Yesterday's assignment: {cond}",
            [
                _tap("Yes", f"{base}/{slug}/log", yesterday, True),
                _tap("No", f"{base}/{slug}/log", yesterday, False),
            ],
        )
        for slug, cond in due
    ]
