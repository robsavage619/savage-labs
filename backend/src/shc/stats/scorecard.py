"""Monthly scorecard: is the engine helping, measured against simple comparators.

Read-only, computed from existing tables. The decision rules live in
docs/evaluation.md and were committed before any review, so the numbers can't
choose their own interpretation.
"""

from __future__ import annotations

import json
import math
import statistics as st
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import duckdb

from shc.training.load_mechanics import per_hand_kg
from shc.training.self_learning import accuracy_baseline

_WINDOW_DAYS = 90
_LB_PER_KG = 2.20462
# Lifts whose logged unit never changed, so a trend across dates is meaningful.
_FIXED_LIFTS = (
    "Hammerstrength Incline Chest Press",
    "Leg Extension (Machine)",
    "Hammerstrength Shoulder Press",
    "Barbell Bicep Drag Curl",
    "Cable Rope Hammer Curls",
    "Hip Abduction (Machine)",
    "V-Bar Pulldown",
    "Seated Leg Curl (Machine)",
)
# A session residual past this is a logging-unit change, not a performance change.
_MAX_PLAUSIBLE_RESIDUAL = 0.3


def _status(ok: bool | None) -> str:
    return "not measured" if ok is None else ("on track" if ok else "review")


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _execution(conn: duckdb.DuckDBPyConnection, since: date) -> dict[str, Any]:
    """Adherence and load accuracy for lifting plans since ``since``."""
    logged: dict[date, dict[str, list[tuple[float, int, float | None]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for day, exercise, weight, reps, rpe in conn.execute(
        """
        SELECT started_at::DATE, exercise, weight_kg, reps, rpe FROM workout_sets_dedup
        WHERE NOT is_warmup AND started_at::DATE >= ?
        """,
        [since],
    ).fetchall():
        logged[day][exercise].append((float(weight or 0) * _LB_PER_KG, reps or 0, rpe))

    plans = sessions = ex_total = ex_done = sets_total = sets_done = 0
    load_total = load_hit = reps_total = reps_hit = rpe_total = rpe_echo = 0
    for day, plan_json in conn.execute(
        "SELECT date, plan_json FROM workout_plans WHERE date >= ? AND date < CURRENT_DATE",
        [since],
    ).fetchall():
        try:
            blocks = json.loads(plan_json).get("blocks", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
        exercises = [
            e
            for b in blocks
            for e in b.get("exercises", [])
            if isinstance(e, dict) and e.get("rpe_target") and (e.get("rpe_target") or 0) >= 6
        ]
        if not exercises:
            continue
        plans += 1
        done_today = logged.get(day)
        if done_today is None:
            continue  # a skipped day counts once above, not against every exercise
        sessions += 1
        for ex in exercises:
            planned_sets = ex.get("sets") if isinstance(ex.get("sets"), int) else 0
            ex_total += 1
            sets_total += planned_sets
            rows = done_today.get(ex.get("name"), [])
            ex_done += bool(rows)
            sets_done += min(planned_sets, len(rows))
            if not rows:
                continue
            target = ex.get("weight_lbs")
            if target:
                load_total += 1
                load_hit += abs(max(r[0] for r in rows) / target - 1) <= 0.05
            bounds = [
                int(n) for n in str(ex.get("reps")).replace("–", "-").split("-") if n.isdigit()
            ]
            if bounds:
                for _, reps, _ in rows:
                    reps_total += 1
                    reps_hit += min(bounds) <= reps <= max(bounds)
            for *_, rpe in rows:
                if rpe is not None:
                    rpe_total += 1
                    rpe_echo += float(rpe) == float(ex["rpe_target"])
    return {
        "plans": plans,
        "plans_with_session_pct": _pct(sessions, plans),
        "exercises_done_pct": _pct(ex_done, ex_total),
        "sets_done_pct": _pct(sets_done, sets_total),
        "top_weight_within_5pct": _pct(load_hit, load_total),
        "reps_in_range_pct": _pct(reps_hit, reps_total),
        "rpe_echo_pct": _pct(rpe_echo, rpe_total),
    }


def _session_residuals(conn: duckdb.DuckDBPyConnection) -> list[tuple[date, float, float | None]]:
    """(day, top-set raw e1RM vs that lift's recent sessions, morning score), by session."""
    best: dict[str, dict[date, float]] = defaultdict(dict)
    for day, exercise, weight, reps in conn.execute(
        """
        SELECT started_at::DATE, exercise, weight_kg, reps FROM workout_sets_dedup
        WHERE NOT is_warmup AND weight_kg > 0 AND reps > 0
          AND started_at::DATE >= CURRENT_DATE - INTERVAL 730 DAY
        """
    ).fetchall():
        e1rm = per_hand_kg(exercise, weight, day) * (1 + min(reps, 12) / 30)
        if e1rm > best[exercise].get(day, 0.0):
            best[exercise][day] = e1rm
    by_day: dict[date, list[float]] = defaultdict(list)
    for sessions in best.values():
        days = sorted(sessions)
        for i, day in enumerate(days):
            prior = [sessions[d] for d in days[max(0, i - 4) : i] if (day - d).days <= 120]
            if len(prior) >= 2:
                residual = math.log(sessions[day] / st.mean(prior))
                if abs(residual) <= _MAX_PLAUSIBLE_RESIDUAL:
                    by_day[day].append(residual)
    scores = dict(conn.execute("SELECT date, score FROM recovery").fetchall())
    return [(d, st.mean(v), scores.get(d)) for d, v in sorted(by_day.items()) if len(v) >= 2]


def _readiness_skill(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Held-out RMSE skill of WHOOP score against the training-period mean."""
    rows = [(s, r) for _, r, s in _session_residuals(conn) if s is not None]
    if len(rows) < 60:
        return {"n": len(rows), "skill_pct": None}
    cut = int(len(rows) * 2 / 3)
    train, test = rows[:cut], rows[cut:]
    mean_s, mean_r = st.mean(s for s, _ in train), st.mean(r for _, r in train)
    var_s = sum((s - mean_s) ** 2 for s, _ in train)
    slope = sum((s - mean_s) * (r - mean_r) for s, r in train) / var_s if var_s else 0.0
    baseline = math.sqrt(st.mean((r - mean_r) ** 2 for _, r in test))
    model = math.sqrt(st.mean((r - (mean_r + slope * (s - mean_s))) ** 2 for s, r in test))
    return {
        "n": len(rows),
        "skill_pct": round(100.0 * (1 - model / baseline), 1) if baseline else None,
    }


def _adaptation(conn: duckdb.DuckDBPyConnection, today: date) -> dict[str, Any]:
    """Median change on the fixed lifts, latest 90 days against the 90 before."""
    mid, start = today - timedelta(days=_WINDOW_DAYS), today - timedelta(days=2 * _WINDOW_DAYS)
    changes = []
    for lift in _FIXED_LIFTS:
        rows = conn.execute(
            """
            SELECT started_at::DATE, MAX(weight_kg * (1 + LEAST(reps, 12) / 30.0))
            FROM workout_sets_dedup
            WHERE exercise = ? AND NOT is_warmup AND weight_kg > 0 AND reps > 0
              AND started_at::DATE >= ?
            GROUP BY 1
            """,
            [lift, start],
        ).fetchall()
        before, after = [v for d, v in rows if d < mid], [v for d, v in rows if d >= mid]
        if len(before) >= 3 and len(after) >= 3:
            changes.append(100.0 * (st.median(after) / st.median(before) - 1))
    return {
        "lifts": len(changes),
        "median_change_pct": round(st.median(changes), 1) if changes else None,
    }


def _outcomes(conn: duckdb.DuckDBPyConnection, since: date, today: date) -> dict[str, Any]:
    """Real body measurements only. WHOOP's repeated profile weight doesn't count."""
    scale = conn.execute(
        """
        SELECT COUNT(*), MAX(d) FROM (
            SELECT ts::DATE AS d FROM measurements
            WHERE metric = 'body_mass_kg' AND ts::DATE >= $s
            UNION ALL
            SELECT date FROM daily_checkin WHERE body_weight_kg IS NOT NULL AND date >= $s
        )
        """,
        {"s": since},
    ).fetchone()
    tape = conn.execute(
        "SELECT COUNT(*) FROM measurements WHERE metric = 'waist_circumference_cm' AND ts::DATE >= ?",
        [since],
    ).fetchone()
    photos = conn.execute(
        "SELECT COUNT(DISTINCT photo_date) FROM progress_photos WHERE photo_date >= ?",
        [since],
    ).fetchone()
    trained = {
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT date_trunc('week', started_at::DATE)::DATE FROM workout_sets_dedup
            WHERE NOT is_warmup AND started_at::DATE >= ?
            """,
            [since],
        ).fetchall()
    }
    monday = today - timedelta(days=today.weekday())
    weeks = [monday - timedelta(weeks=i) for i in range(1, _WINDOW_DAYS // 7 + 1)]
    return {
        "scale_readings": scale[0] if scale else 0,
        "last_scale_reading": str(scale[1]) if scale and scale[1] else None,
        "tape_readings": tape[0] if tape else 0,
        "photo_sessions": photos[0] if photos else 0,
        "zero_training_weeks": sum(w not in trained for w in weeks if w >= since),
    }


def scorecard(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict[str, Any]:
    """Build the six-metric scorecard over the latest 90 days."""
    today = today or date.today()
    since = today - timedelta(days=_WINDOW_DAYS)
    ex = _execution(conn, since)
    baseline = accuracy_baseline(conn)
    readiness = _readiness_skill(conn)
    adapt = _adaptation(conn, today)
    body = _outcomes(conn, since, today)

    done = ex["exercises_done_pct"]
    weight = ex["top_weight_within_5pct"]
    echo = ex["rpe_echo_pct"]
    gap = round(100 * (baseline["logged"] - baseline["shuffled"]), 1) if baseline else None
    skill = readiness["skill_pct"]
    change = adapt["median_change_pct"]
    measured = body["scale_readings"] >= 6 and body["tape_readings"] >= 2

    return {
        "as_of": today.isoformat(),
        "window_days": _WINDOW_DAYS,
        "first_review": "2027-05-01",
        "metrics": [
            {
                "key": "adherence",
                "label": "Exercises done on days he trained",
                "value": done,
                "unit": "%",
                "status": _status(None if done is None else done >= 60),
                "detail": ex,
            },
            {
                "key": "load_accuracy",
                "label": "Top weight within 5% of plan",
                "value": weight,
                "unit": "%",
                "status": _status(None if weight is None else weight >= 60),
                "detail": {"reps_in_range_pct": ex["reps_in_range_pct"], "rpe_echo_pct": echo},
            },
            {
                "key": "call_skill",
                "label": "Volume calls above chance",
                "value": gap,
                "unit": " pts",
                "status": _status(None if gap is None else gap >= 3),
                "detail": baseline or {},
            },
            {
                "key": "readiness_skill",
                "label": "Readiness forecast skill",
                "value": skill,
                "unit": "%",
                "status": _status(None if skill is None else skill >= 2),
                "detail": readiness,
            },
            {
                "key": "adaptation",
                "label": "Fixed-lift strength, latest 90 days vs prior 90",
                "value": change,
                "unit": "%",
                "status": _status(None if change is None else change > 0),
                "detail": adapt,
            },
            {
                "key": "outcomes",
                "label": "Size and weight measured",
                "value": body["tape_readings"],
                "unit": " tape readings",
                "status": _status(True if measured else None),
                "detail": body,
            },
        ],
    }
