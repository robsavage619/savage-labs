"""Weekly body scorecard: did the last 7 days move, beyond Rob's own noise?

Read-only. Each domain compares its last-7-day mean to the 28 daily values
before it, through ``classify_change`` so a delta inside the personal noise
floor reads "steady", never "better" or "worse". Nothing here feeds a gate.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import duckdb

from shc.stats.noise_floor import classify_change

_WEEK = 7
_BASELINE_DAYS = 28
_MIN_WEEK_DAYS = 4
# +1 when a rise is the good direction, -1 when a fall is.
_POLARITY = {"hrv": 1, "rhr": -1, "sleep_h": 1, "stress": -1, "work_sets": 0}
_LABEL = {
    "hrv": "HRV",
    "rhr": "Resting HR",
    "sleep_h": "Sleep (h)",
    "stress": "Stress",
    "work_sets": "Working sets/day",
}


def _daily(conn: duckdb.DuckDBPyConnection, sql: str, start: date, end: date) -> dict[date, float]:
    rows = conn.execute(sql, [start, end]).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _series(conn: duckdb.DuckDBPyConnection, end: date) -> dict[str, dict[date, float]]:
    start = end - timedelta(days=_WEEK + _BASELINE_DAYS - 1)
    return {
        "hrv": _daily(
            conn,
            "SELECT date, avg(hrv) FROM recovery WHERE date BETWEEN ? AND ? GROUP BY 1",
            start,
            end,
        ),
        "rhr": _daily(
            conn,
            "SELECT date, avg(rhr) FROM recovery WHERE date BETWEEN ? AND ? GROUP BY 1",
            start,
            end,
        ),
        "sleep_h": _daily(
            conn,
            "SELECT night_date, max(epoch(ts_out - ts_in)) / 3600.0 FROM sleep "
            "WHERE night_date BETWEEN ? AND ? GROUP BY 1",
            start,
            end,
        ),
        "stress": _daily(
            conn,
            "SELECT date, avg(value) FROM whoop_stress_timeline "
            "WHERE date BETWEEN ? AND ? GROUP BY 1",
            start,
            end,
        ),
        "work_sets": _daily(
            conn,
            "SELECT day_d, count(*) FROM workout_sets_dedup "
            "WHERE NOT coalesce(is_warmup, false) AND day_d BETWEEN ? AND ? GROUP BY 1",
            start,
            end,
        ),
    }


def _verdict(key: str, by_day: dict[date, float], end: date) -> dict[str, Any]:
    week_days = [end - timedelta(days=i) for i in range(_WEEK)]
    base_days = [end - timedelta(days=_WEEK + i) for i in range(_BASELINE_DAYS)]
    if key == "work_sets":  # a rest day is a real zero, not a missing night
        week = [by_day.get(d, 0.0) for d in week_days]
        base = [by_day.get(d, 0.0) for d in base_days]
    else:
        week = [by_day[d] for d in week_days if d in by_day]
        base = [by_day[d] for d in base_days if d in by_day]
    mean = sum(week) / len(week) if len(week) >= _MIN_WEEK_DAYS else None
    v = classify_change(mean, base).as_dict()
    polarity = _POLARITY[key]
    if v["direction"] in ("flat", "unknown") or polarity == 0:
        status = "unknown" if v["direction"] == "unknown" else "steady"
        if v["direction"] in ("up", "down") and polarity == 0:
            status = "moved"
    else:
        status = "better" if (v["direction"] == "up") == (polarity > 0) else "worse"
    return {"key": key, "label": _LABEL[key], "status": status, "days": len(week), **v}


def rpe_gap(conn: duckdb.DuckDBPyConnection, today: date, days: int = 14) -> dict:
    """Working sets with no RPE, by session day, newest first."""
    rows = conn.execute(
        "SELECT day_d, count(*), count(*) FILTER (WHERE rpe IS NULL) "
        "FROM workout_sets_dedup WHERE NOT coalesce(is_warmup, false) "
        "AND day_d BETWEEN ? AND ? GROUP BY 1 ORDER BY 1 DESC",
        [today - timedelta(days=days), today],
    ).fetchall()
    sessions = [{"date": str(d), "sets": n, "missing": m} for d, n, m in rows if n]
    sets = sum(s["sets"] for s in sessions)
    missing = sum(s["missing"] for s in sessions)
    return {
        "sessions": sessions,
        "sets": sets,
        "missing": missing,
        "pct_missing": round(100 * missing / sets) if sets else None,
    }


def weekly_card(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict:
    """The five domain verdicts plus the RPE coverage gap."""
    end = today or date.today()
    series = _series(conn, end)
    return {
        "as_of": str(end),
        "domains": [_verdict(k, series[k], end) for k in _POLARITY],
        "rpe_gap": rpe_gap(conn, end),
    }
