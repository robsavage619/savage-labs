from __future__ import annotations

import json
import logging
import statistics
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from shc.ai.briefing import build_daily_context, store_briefing
from shc.ai.workout_planner import build_training_context, load_plan, save_plan, validate_plan
from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["dashboard"])
log = logging.getLogger(__name__)


class WorkoutPlanSubmission(BaseModel):
    plan: dict[str, Any]
    source: str = "claude"
    push_to_hevy: bool = False


class BriefingSubmission(BaseModel):
    training_call: str  # Push | Train | Maintain | Easy | Rest
    training_rationale: str
    readiness_headline: str
    coaching_note: str
    flags: list[str] = []
    priority_metric: str = "none"


class RetrospectiveSubmission(BaseModel):
    workout_id: str
    summary: str
    progressive_overload_achieved: bool | None = None
    rpe_vs_target: str | None = None
    flags: list[str] = []
    vault_insights: list[str] = []


@router.get("/recovery/today")
async def recovery_today() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT date, score, hrv, rhr, skin_temp FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()
        baseline = conn.execute(
            "SELECT AVG(skin_temp) FROM recovery WHERE skin_temp IS NOT NULL AND date >= (current_date - INTERVAL '28 days')"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    base = float(baseline[0]) if baseline and baseline[0] is not None else None
    return {
        "date": str(row[0]),
        "score": row[1],
        "hrv": row[2],
        "rhr": row[3],
        "skin_temp": row[4],
        "skin_temp_baseline_28d": round(base, 2) if base else None,
        "skin_temp_delta": round(float(row[4]) - base, 2) if (row[4] is not None and base) else None,
    }


@router.get("/recovery/trend")
async def recovery_trend(days: int = Query(14, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT date, score, hrv, rhr FROM recovery WHERE date >= $since ORDER BY date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "score": r[1], "hrv": r[2], "rhr": r[3]} for r in rows]


@router.get("/hrv/trend")
async def hrv_trend(days: int = Query(28, gt=0, le=365)) -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT date, hrv, hrv_28d_avg, hrv_28d_sd
            FROM v_hrv_baseline_28d
            ORDER BY date DESC
            LIMIT $days
            """,
            {"days": days},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "hrv": r[1], "avg": r[2], "sd": r[3]} for r in reversed(rows)]


@router.get("/sleep/recent")
async def sleep_recent(days: int = Query(7, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT night_date, stages_json, spo2_avg, rhr, "
            "epoch(ts_out - ts_in) / 3600.0 AS hours "
            "FROM sleep WHERE night_date >= $since ORDER BY night_date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": str(r[0]), "stages": r[1], "spo2": r[2], "rhr": r[3], "hours": r[4]}
        for r in rows
    ]


@router.get("/sleep/trend")
async def sleep_trend(days: int = Query(30, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT night_date, stages_json, "
            "epoch(ts_out - ts_in) / 3600.0 AS hours "
            "FROM sleep WHERE night_date >= $since ORDER BY night_date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "stages": r[1], "hours": r[2]} for r in rows]


@router.get("/readiness/today")
async def readiness_today() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT date, recovery_score, hrv, rhr, sleep_hours, "
            "energy_1_10, stress_1_10 FROM v_readiness LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {
        "date": str(row[0]),
        "recovery_score": row[1],
        "hrv": row[2],
        "rhr": row[3],
        "sleep_hours": row[4],
        "energy": row[5],
        "stress": row[6],
    }


def _linreg_slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    return num / den


def _streak(values: list[tuple[date, bool]]) -> int:
    """Count trailing consecutive True days from most recent backward."""
    run = 0
    for _, ok in reversed(values):
        if ok:
            run += 1
        else:
            break
    return run


@router.get("/stats/summary")
async def stats_summary() -> dict:
    """Composite stats: ACWR proxy, HRV deviation, sleep consistency, streaks, trend."""
    today = date.today()
    conn = get_read_conn()
    try:
        rec_rows = conn.execute(
            "SELECT date, score, hrv, rhr FROM recovery "
            "WHERE date >= $since ORDER BY date",
            {"since": (today - timedelta(days=90)).isoformat()},
        ).fetchall()
        hrv_rows = conn.execute(
            "SELECT date, hrv, hrv_28d_avg, hrv_28d_sd FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
        ).fetchone()
        sleep_rows = conn.execute(
            "SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS hours "
            "FROM sleep WHERE night_date >= $since ORDER BY night_date",
            {"since": (today - timedelta(days=14)).isoformat()},
        ).fetchall()
    finally:
        conn.close()

    scores_7 = [r[1] for r in rec_rows[-7:] if r[1] is not None]
    scores_28 = [r[1] for r in rec_rows[-28:] if r[1] is not None]
    acute = sum(scores_7) / len(scores_7) if scores_7 else None
    chronic = sum(scores_28) / len(scores_28) if scores_28 else None
    acwr = (acute / chronic) if (acute and chronic) else None

    rhrs_7 = [r[3] for r in rec_rows[-7:] if r[3] is not None]
    rhrs_28 = [r[3] for r in rec_rows[-28:] if r[3] is not None]
    rhr_baseline = sum(rhrs_28) / len(rhrs_28) if rhrs_28 else None
    rhr_7avg = sum(rhrs_7) / len(rhrs_7) if rhrs_7 else None
    rhr_elevated_pct = (
        ((rhr_7avg - rhr_baseline) / rhr_baseline * 100.0)
        if (rhr_baseline and rhr_7avg)
        else None
    )

    hrv_sigma = None
    hrv_today = None
    hrv_baseline = None
    if hrv_rows:
        hrv_today, hrv_baseline, hrv_sd = hrv_rows[1], hrv_rows[2], hrv_rows[3]
        if hrv_today and hrv_baseline and hrv_sd:
            hrv_sigma = (hrv_today - hrv_baseline) / hrv_sd

    sleep_hours_7 = [float(r[1]) for r in sleep_rows[-7:] if r[1] is not None]
    sleep_consistency = (
        statistics.pstdev(sleep_hours_7) if len(sleep_hours_7) >= 2 else None
    )
    sleep_avg_7 = sum(sleep_hours_7) / len(sleep_hours_7) if sleep_hours_7 else None
    sleep_debt_7 = (
        sum(max(0.0, 8.0 - h) for h in sleep_hours_7) if sleep_hours_7 else None
    )

    rec_trend_slope = _linreg_slope(scores_7) if len(scores_7) >= 3 else 0.0

    recovery_streak = _streak(
        [(r[0], (r[1] or 0) > 60) for r in rec_rows[-30:]]
    )
    sleep_streak_rows = [(r[0], (float(r[1]) if r[1] else 0) >= 7.0) for r in sleep_rows[-30:]]
    sleep_streak = _streak(sleep_streak_rows)

    best_hrv = max((r for r in rec_rows if r[2] is not None), key=lambda r: r[2], default=None)
    lowest_rhr = min((r for r in rec_rows if r[3] is not None), key=lambda r: r[3], default=None)

    return {
        "acwr": {"acute": acute, "chronic": chronic, "ratio": acwr},
        "hrv": {
            "today": hrv_today,
            "baseline_28d": hrv_baseline,
            "deviation_sigma": hrv_sigma,
        },
        "rhr": {
            "baseline_28d": rhr_baseline,
            "last_7_avg": rhr_7avg,
            "elevated_pct": rhr_elevated_pct,
        },
        "sleep": {
            "consistency_stdev": sleep_consistency,
            "avg_7d": sleep_avg_7,
            "debt_7d_hours": sleep_debt_7,
        },
        "recovery_trend_slope_7d": rec_trend_slope,
        "streaks": {
            "recovery_above_60": recovery_streak,
            "sleep_above_7h": sleep_streak,
        },
        "personal_bests": {
            "best_hrv": (
                {"date": str(best_hrv[0]), "hrv": best_hrv[2]} if best_hrv else None
            ),
            "lowest_rhr": (
                {"date": str(lowest_rhr[0]), "rhr": lowest_rhr[3]} if lowest_rhr else None
            ),
        },
    }


@router.get("/insights")
async def insights() -> list[dict]:
    """Auto-derived coach-style observations from the last 90 days."""
    today = date.today()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT r.date, r.score, r.hrv, r.rhr, "
            "epoch(s.ts_out - s.ts_in) / 3600.0 AS hours "
            "FROM recovery r "
            "LEFT JOIN sleep s ON s.night_date = r.date AND s.source = r.source "
            "WHERE r.date >= $since ORDER BY r.date",
            {"since": (today - timedelta(days=90)).isoformat()},
        ).fetchall()
    finally:
        conn.close()

    items: list[dict] = []
    by_date = {r[0]: r for r in rows}
    dates = sorted(by_date.keys())

    long_sleep_next_hrv = []
    short_sleep_next_hrv = []
    for i, d in enumerate(dates[:-1]):
        today_row = by_date[d]
        next_row = by_date[dates[i + 1]]
        if today_row[4] and next_row[2]:
            if float(today_row[4]) >= 7.5:
                long_sleep_next_hrv.append(next_row[2])
            elif float(today_row[4]) < 6.5:
                short_sleep_next_hrv.append(next_row[2])

    if long_sleep_next_hrv and short_sleep_next_hrv:
        delta = sum(long_sleep_next_hrv) / len(long_sleep_next_hrv) - sum(
            short_sleep_next_hrv
        ) / len(short_sleep_next_hrv)
        verb = "lifts" if delta > 0 else "lowers"
        items.append(
            {
                "headline": f"Long sleep {verb} next-day HRV by {abs(delta):.1f}ms",
                "body": (
                    f"When you sleep ≥7.5h, next-day HRV averages "
                    f"{sum(long_sleep_next_hrv) / len(long_sleep_next_hrv):.1f}ms vs "
                    f"{sum(short_sleep_next_hrv) / len(short_sleep_next_hrv):.1f}ms after <6.5h nights."
                ),
                "polarity": "positive" if delta > 0 else "negative",
            }
        )

    dow_scores: dict[int, list[float]] = {}
    for r in rows:
        if r[1] is None:
            continue
        dow = datetime.fromisoformat(str(r[0])).weekday()
        dow_scores.setdefault(dow, []).append(r[1])
    if dow_scores:
        means = {d: sum(v) / len(v) for d, v in dow_scores.items() if v}
        best = max(means, key=means.get)
        worst = min(means, key=means.get)
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        delta = means[best] - means[worst]
        if delta >= 4:
            items.append(
                {
                    "headline": f"{labels[best]} is your strongest recovery day",
                    "body": (
                        f"{labels[best]} averages {means[best]:.0f} vs {labels[worst]} at "
                        f"{means[worst]:.0f}  ({delta:+.0f} pt gap)."
                    ),
                    "polarity": "neutral",
                }
            )

    below_baseline = []
    scores = [r[1] for r in rows if r[1] is not None]
    if len(scores) >= 14:
        baseline = sum(scores[-28:]) / min(28, len(scores))
        low_days = [r for r in rows[-14:] if r[1] and r[1] < baseline - 10]
        for lr in low_days:
            idx = dates.index(lr[0])
            window = rows[max(0, idx - 2) : idx]
            window_hrvs = [w[2] for w in window if w[2]]
            if window_hrvs and lr[2]:
                below_baseline.append(lr[2] - sum(window_hrvs) / len(window_hrvs))
        if below_baseline:
            avg_drop = sum(below_baseline) / len(below_baseline)
            if avg_drop < -3:
                items.append(
                    {
                        "headline": f"HRV drops ~{abs(avg_drop):.0f}ms ahead of low-recovery days",
                        "body": (
                            "Days flagged low recovery are preceded by HRV "
                            f"{avg_drop:+.1f}ms vs the prior 48h  — watch load when HRV dips."
                        ),
                        "polarity": "negative",
                    }
                )

    # ── VO₂ max trend insight ──────────────────────────────────────────────
    conn2 = get_read_conn()
    try:
        vo2_rows = conn2.execute(
            "SELECT ts::DATE AS day, AVG(value_num) AS v FROM measurements "
            "WHERE metric = 'vo2_max' GROUP BY day ORDER BY day"
        ).fetchall()
        wt_rows = conn2.execute(
            "SELECT ts::DATE AS day, AVG(value_num) AS kg FROM measurements "
            "WHERE metric = 'body_mass_kg' GROUP BY day ORDER BY day"
        ).fetchall()
    finally:
        conn2.close()

    if vo2_rows and len(vo2_rows) >= 10:
        peak_row = max(vo2_rows, key=lambda r: r[1])
        current = vo2_rows[-1][1]
        peak = peak_row[1]
        peak_date = str(peak_row[0])[:7]
        delta = current - peak

        if delta < -5:
            # weight-adjusted attribution — nearest date to peak
            peak_date_str = str(peak_row[0])[:10]
            wt_at_peak = None
            if wt_rows:
                nearest = min(wt_rows, key=lambda r: abs((date.fromisoformat(str(r[0])[:10]) - date.fromisoformat(peak_date_str)).days))
                if abs((date.fromisoformat(str(nearest[0])[:10]) - date.fromisoformat(peak_date_str)).days) <= 365:
                    wt_at_peak = nearest[1]
            wt_current = wt_rows[-1][1] if wt_rows else None
            wt_note = ""
            if wt_at_peak and wt_current and wt_current > wt_at_peak:
                wt_delta_kg = wt_current - wt_at_peak
                # if absolute VO2 unchanged, VO2max change = v_peak * (wt_peak/wt_current - 1)
                wt_effect = round(peak * (wt_at_peak / wt_current - 1), 1)
                true_fitness_delta = round(delta - wt_effect, 1)
                wt_note = (
                    f" Weight gain (+{wt_delta_kg:.0f}kg) accounts for ~{abs(wt_effect):.1f} mL/kg/min; "
                    f"true aerobic fitness decline is ~{abs(true_fitness_delta):.1f} mL/kg/min."
                )
            items.insert(0, {
                "headline": f"VO₂ max down {abs(delta):.1f} mL/kg/min from {peak:.1f} peak ({peak_date})",
                "body": (
                    f"Current {current:.1f} vs peak {peak:.1f} mL/kg/min — "
                    f"~4× the expected age-related rate of decline (0.4/yr).{wt_note} "
                    f"Priority: zone 2 cardio 3×/wk and progressive weight reduction."
                ),
                "polarity": "negative",
            })

    if not items:
        items.append(
            {
                "headline": "Still learning your patterns",
                "body": "Keep syncing — correlations surface after ~14 days of data.",
                "polarity": "neutral",
            }
        )
    return items


@router.get("/personal-bests")
async def personal_bests() -> dict:
    conn = get_read_conn()
    try:
        top_hrv = conn.execute(
            "SELECT date, hrv FROM recovery WHERE hrv IS NOT NULL "
            "ORDER BY hrv DESC LIMIT 5"
        ).fetchall()
        low_rhr = conn.execute(
            "SELECT date, rhr FROM recovery WHERE rhr IS NOT NULL "
            "ORDER BY rhr ASC LIMIT 5"
        ).fetchall()
        top_sleep = conn.execute(
            "SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS h "
            "FROM sleep WHERE ts_out IS NOT NULL AND ts_in IS NOT NULL "
            "ORDER BY h DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    return {
        "top_hrv": [{"date": str(r[0]), "value": r[1]} for r in top_hrv],
        "lowest_rhr": [{"date": str(r[0]), "value": r[1]} for r in low_rhr],
        "longest_sleep": [{"date": str(r[0]), "value": r[1]} for r in top_sleep],
    }


@router.get("/week/summary")
async def week_summary() -> list[dict]:
    """Mon–Sun blocks for the current week with recovery + sleep."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = get_read_conn()
    try:
        rec = conn.execute(
            "SELECT date, score FROM recovery WHERE date >= $m AND date <= $s",
            {"m": monday.isoformat(), "s": (monday + timedelta(days=6)).isoformat()},
        ).fetchall()
        sleep = conn.execute(
            "SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS h "
            "FROM sleep WHERE night_date >= $m AND night_date <= $s",
            {"m": monday.isoformat(), "s": (monday + timedelta(days=6)).isoformat()},
        ).fetchall()
    finally:
        conn.close()
    rec_map = {str(r[0]): r[1] for r in rec}
    sleep_map = {str(r[0]): r[1] for r in sleep}
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = []
    for i in range(7):
        d = monday + timedelta(days=i)
        iso = d.isoformat()
        out.append(
            {
                "label": labels[i],
                "date": iso,
                "is_today": d == today,
                "is_future": d > today,
                "recovery": rec_map.get(iso),
                "sleep_hours": sleep_map.get(iso),
            }
        )
    return out


@router.get("/training/last-session")
async def training_last_session() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT
                started_at::DATE AS day,
                COUNT(*) AS set_count,
                COUNT(DISTINCT exercise) AS exercise_count,
                SUM(weight_kg * reps) AS volume_kg,
                ARRAY_AGG(DISTINCT exercise ORDER BY exercise) AS exercises
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
            GROUP BY day
            ORDER BY day DESC
            LIMIT 1
            """
        ).fetchone()
        week_row = conn.execute(
            """
            SELECT COUNT(*), SUM(weight_kg * reps)
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND started_at::DATE >= date_trunc('week', current_date)::DATE
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    today = date.today()
    days_ago = (today - row[0]).days
    return {
        "date": str(row[0]),
        "days_ago": days_ago,
        "sets": row[1],
        "exercises": row[2],
        "volume_kg": round(row[3] or 0, 1),
        "exercise_list": list(row[4] or [])[:6],
        "week_sets": week_row[0] if week_row else 0,
        "week_volume_kg": round(week_row[1] or 0, 1) if week_row else 0,
    }


@router.get("/training/heatmap")
async def training_heatmap(weeks: int = Query(104, gt=0, le=260)) -> list[dict]:
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                started_at::DATE AS day,
                COUNT(*) AS set_count,
                SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE AND started_at::DATE >= $since
            GROUP BY day
            ORDER BY day
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []
    max_vol = max(r[2] or 0 for r in rows) or 1
    result = []
    for r in rows:
        vol = r[2] or 0
        intensity = min(4, int((vol / max_vol) * 4) + 1) if vol > 0 else 0
        result.append({"date": str(r[0]), "intensity": intensity, "sets": r[1], "volume_kg": round(vol, 1)})
    return result


@router.get("/training/weekly")
async def training_weekly(weeks: int = Query(52, gt=0, le=260)) -> list[dict]:
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                date_trunc('week', started_at)::DATE AS week,
                COUNT(*) AS sets,
                SUM(weight_kg * reps) AS volume_kg,
                COUNT(DISTINCT started_at::DATE) AS sessions
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND weight_kg IS NOT NULL
              AND reps IS NOT NULL
              AND started_at::DATE >= $since
            GROUP BY week
            ORDER BY week
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"week": str(r[0]), "sets": r[1], "volume_kg": round(r[2] or 0, 1), "sessions": r[3]} for r in rows]


@router.get("/training/prs")
async def training_prs(n: int = Query(15, gt=0, le=100)) -> list[dict]:
    """PRs ranked by max weight, with reps-at-PR + Epley estimated 1RM.

    Epley: 1RM = weight * (1 + reps/30). For a true 1-rep set this collapses
    to the lifted weight.
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            WITH pr AS (
                SELECT
                    ws.exercise,
                    MAX(ws.weight_kg) AS pr_kg
                FROM workout_sets ws
                JOIN workouts w ON w.id = ws.workout_id
                WHERE ws.is_warmup = FALSE
                  AND weight_kg IS NOT NULL
                  AND weight_kg > 20
                  AND weight_kg < 300
                  AND reps IS NOT NULL AND reps > 0
                  AND NOT regexp_matches(lower(exercise),
                    'plank|push.?up|pull.?up|chin.?up|dip|crunch|sit.?up|burpee|'
                    'box.jump|jump|lunge|squat air|air squat|scissor|superman|'
                    'mountain.climb|bicycle|flutter|leg raise|hollow|bear crawl|'
                    'russian twist|oblique|twist|v.?up|tuck|hyperextension')
                GROUP BY ws.exercise
                HAVING COUNT(*) >= 5 AND STDDEV(weight_kg) > 2
            ),
            pr_set AS (
                SELECT
                    pr.exercise,
                    pr.pr_kg,
                    MAX(ws.reps) AS pr_reps,
                    MAX(w.started_at::DATE) AS pr_date,
                    MAX(w2.last) AS last_performed
                FROM pr
                JOIN workout_sets ws ON ws.exercise = pr.exercise AND ws.weight_kg = pr.pr_kg
                JOIN workouts w ON w.id = ws.workout_id
                JOIN (
                    SELECT exercise, MAX(started_at::DATE) AS last
                    FROM workout_sets ws3 JOIN workouts w3 ON w3.id = ws3.workout_id
                    GROUP BY exercise
                ) w2 ON w2.exercise = pr.exercise
                GROUP BY pr.exercise, pr.pr_kg
            )
            SELECT exercise, pr_kg, pr_reps, pr_date, last_performed
            FROM pr_set
            ORDER BY pr_kg DESC
            LIMIT $n
            """,
            {"n": n},
        ).fetchall()
    finally:
        conn.close()

    out = []
    for ex, pr_kg, pr_reps, pr_date, last in rows:
        reps = int(pr_reps or 1)
        est_1rm_kg = float(pr_kg) * (1 + reps / 30.0)
        out.append({
            "exercise": ex,
            "pr_lbs": round(pr_kg * 2.20462, 1),
            "pr_kg": round(pr_kg, 1),
            "pr_reps": reps,
            "pr_date": str(pr_date),
            "est_1rm_lbs": round(est_1rm_kg * 2.20462, 1),
            "est_1rm_kg": round(est_1rm_kg, 1),
            "last_performed": str(last),
        })
    return out


@router.get("/training/exercise-last")
async def training_exercise_last(exercise: str = Query(..., description="Exercise name (substring, case-insensitive)")) -> dict:
    """Return the most recent working set for an exercise — used as the
    plan-vs-history anchor on the Next Workout view (`last: 185×5 @ RPE 8`).
    """
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT
                ws.exercise,
                w.started_at::DATE AS day,
                ws.weight_kg,
                ws.reps,
                ws.rpe
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND LOWER(ws.exercise) LIKE $pat
              AND ws.weight_kg IS NOT NULL
              AND ws.reps IS NOT NULL AND ws.reps > 0
            ORDER BY w.started_at DESC, ws.weight_kg DESC
            LIMIT 1
            """,
            {"pat": f"%{exercise.lower()}%"},
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"found": False, "exercise": exercise}
    ex, day, wkg, reps, rpe = row
    return {
        "found": True,
        "exercise": ex,
        "date": str(day),
        "weight_kg": round(wkg, 1),
        "weight_lbs": round(wkg * 2.20462, 1),
        "reps": int(reps),
        "rpe": float(rpe) if rpe is not None else None,
    }


@router.get("/training/top-exercises")
async def training_top_exercises(n: int = Query(10, gt=0, le=100)) -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                exercise,
                COUNT(*) AS total_sets,
                SUM(weight_kg * reps) AS total_volume_kg,
                MAX(weight_kg) AS pr_kg,
                COUNT(DISTINCT started_at::DATE) AS training_days,
                MAX(started_at::DATE) AS last_performed
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE AND weight_kg IS NOT NULL AND weight_kg > 20
            GROUP BY exercise
            HAVING STDDEV(weight_kg) > 1
            ORDER BY total_sets DESC
            LIMIT $n
            """,
            {"n": n},
        ).fetchall()
        slope_rows = conn.execute(
            """
            SELECT
                date_trunc('week', started_at)::DATE AS week,
                SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND started_at::DATE >= (current_date - INTERVAL '16 weeks')
            GROUP BY week
            ORDER BY week
            """
        ).fetchall()
    finally:
        conn.close()

    weeks_vol = [r[1] for r in slope_rows]
    half = len(weeks_vol) // 2
    prior = sum(weeks_vol[:half]) / max(half, 1) if half else 0
    recent = sum(weeks_vol[half:]) / max(len(weeks_vol) - half, 1) if weeks_vol else 0
    overload_pct = ((recent - prior) / prior * 100) if prior > 0 else None

    exercises = [
        {
            "exercise": r[0],
            "total_sets": r[1],
            "total_volume_kg": round(r[2] or 0, 1),
            "pr_lbs": round(r[3] * 2.20462, 1),
            "training_days": r[4],
            "last_performed": str(r[5]),
        }
        for r in rows
    ]
    return exercises


@router.get("/training/overload-signal")
async def training_overload_signal() -> dict:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                date_trunc('week', started_at)::DATE AS week,
                SUM(weight_kg * reps) AS volume_kg,
                COUNT(*) AS sets,
                COUNT(DISTINCT started_at::DATE) AS days
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND started_at::DATE >= (current_date - INTERVAL '16 weeks')
            GROUP BY week
            ORDER BY week
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"overload_pct": None, "trend": "insufficient_data", "recent_sessions_per_week": None}

    weeks_vol = [float(r[1] or 0) for r in rows]
    half = len(weeks_vol) // 2
    prior_avg = sum(weeks_vol[:half]) / max(half, 1) if half else 0
    recent_avg = sum(weeks_vol[half:]) / max(len(weeks_vol) - half, 1) if weeks_vol else 0
    overload_pct = ((recent_avg - prior_avg) / prior_avg * 100) if prior_avg > 0 else None

    days_recent = [r[3] for r in rows[half:]]
    sessions_per_week = sum(days_recent) / max(len(days_recent), 1) if days_recent else None

    trend = (
        "progressing" if overload_pct and overload_pct > 5
        else "maintaining" if overload_pct and overload_pct > -5
        else "deloading" if overload_pct is not None
        else "insufficient_data"
    )

    return {
        "overload_pct": round(overload_pct, 1) if overload_pct is not None else None,
        "prior_avg_kg": round(prior_avg, 1),
        "recent_avg_kg": round(recent_avg, 1),
        "trend": trend,
        "recent_sessions_per_week": round(sessions_per_week, 1) if sessions_per_week else None,
    }


class CardioLog(BaseModel):
    date: str | None = None
    modality: str
    duration_min: int
    avg_hr: int | None = None
    rpe: float | None = None
    notes: str | None = None


@router.post("/cardio/log")
async def cardio_log(body: CardioLog) -> dict:
    """Log a cardio session (pickleball, walking, biking, etc.)."""
    import hashlib
    import uuid
    d = body.date or date.today().isoformat()
    cid = str(uuid.uuid4())
    payload = f"{d}|{body.modality}|{body.duration_min}|{body.avg_hr}|{body.rpe}|{body.notes or ''}"
    chash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO cardio_sessions
              (id, date, modality, duration_min, avg_hr, rpe, zone_distribution_json, content_hash)
            VALUES ($id, $d, $m, $dur, $hr, $rpe, NULL, $h)
            """,
            {"id": cid, "d": d, "m": body.modality, "dur": body.duration_min, "hr": body.avg_hr, "rpe": body.rpe, "h": chash},
        )
    return {"status": "ok", "id": cid, "date": d}


@router.delete("/cardio/log/{cid}")
async def cardio_delete(cid: str) -> dict:
    async with write_ctx() as conn:
        conn.execute("DELETE FROM cardio_sessions WHERE id = $id", {"id": cid})
    return {"status": "ok", "id": cid}


@router.get("/_diag/sql")
async def diag_sql(q: str = Query(..., description="Read-only SELECT query")) -> dict:
    """Local-only: execute a one-shot SELECT to inspect data shape. Refuses
    anything that isn't a SELECT to keep accidents impossible."""
    if not q.strip().lower().startswith("select"):
        raise HTTPException(status_code=400, detail="SELECT only")
    conn = get_read_conn()
    try:
        rows = conn.execute(q).fetchall()
        cols = [d[0] for d in conn.description] if conn.description else []
    finally:
        conn.close()
    return {"columns": cols, "rows": [list(r) for r in rows[:200]]}


@router.get("/cardio/recent")
async def cardio_recent(days: int = Query(60, gt=0, le=365)) -> dict:
    """Recent non-strength activity: WHOOP/Apple workouts + cardio_sessions.

    Surfaces pickleball, walking, biking, etc. — anything tracked outside
    the Hevy lifting log. Used to power the Cardio & Sports panel.
    """
    conn = get_read_conn()
    try:
        # Strength sessions live in workout_sets — we want everything that
        # ISN'T already represented as a lifting session today.
        sessions = conn.execute(
            """
            SELECT
                w.id,
                w.started_at::DATE AS day,
                w.started_at,
                w.ended_at,
                COALESCE(w.kind, 'workout') AS kind,
                w.strain,
                w.avg_hr,
                w.max_hr,
                w.kcal,
                w.source,
                EXTRACT(epoch FROM (w.ended_at - w.started_at)) / 60 AS duration_min
            FROM workouts w
            WHERE w.started_at::DATE >= (current_date - $d * INTERVAL '1 day')
              AND NOT EXISTS (
                  SELECT 1 FROM workout_sets ws WHERE ws.workout_id = w.id
              )
            ORDER BY w.started_at DESC
            LIMIT 200
            """,
            {"d": days},
        ).fetchall()

        cardio = conn.execute(
            """
            SELECT id, date, modality, duration_min, avg_hr, rpe, zone_distribution_json
            FROM cardio_sessions
            WHERE date >= (current_date - $d * INTERVAL '1 day')
            ORDER BY date DESC
            LIMIT 200
            """,
            {"d": days},
        ).fetchall()
    finally:
        conn.close()

    items = []
    for sid, day, start, end, kind, strain, avg_hr, max_hr, kcal, source, dur in sessions:
        items.append({
            "id": sid,
            "date": str(day),
            "started_at": str(start) if start else None,
            "kind": (kind or "workout").lower(),
            "strain": round(float(strain), 1) if strain is not None else None,
            "avg_hr": int(avg_hr) if avg_hr is not None else None,
            "max_hr": int(max_hr) if max_hr is not None else None,
            "kcal": round(float(kcal)) if kcal is not None else None,
            "duration_min": round(float(dur)) if dur is not None else None,
            "source": source,
        })
    for cid, day, mod, dur, avg_hr, rpe, zones_json in cardio:
        items.append({
            "id": cid,
            "date": str(day),
            "started_at": None,
            "kind": (mod or "cardio").lower(),
            "strain": None,
            "avg_hr": int(avg_hr) if avg_hr is not None else None,
            "max_hr": None,
            "kcal": None,
            "duration_min": int(dur) if dur is not None else None,
            "source": "manual",
            "rpe": float(rpe) if rpe is not None else None,
        })

    items.sort(key=lambda r: r["date"], reverse=True)

    # Aggregate weekly cardio minutes & top modalities for the panel header.
    by_kind: dict[str, dict] = {}
    cutoff = (date.today() - timedelta(days=28)).isoformat()
    for s in items:
        if s["date"] < cutoff:
            continue
        k = s["kind"]
        b = by_kind.setdefault(k, {"sessions": 0, "minutes": 0, "kcal": 0, "strain": 0.0})
        b["sessions"] += 1
        b["minutes"] += s.get("duration_min") or 0
        b["kcal"] += s.get("kcal") or 0
        if s.get("strain"):
            b["strain"] += s["strain"]

    summary = sorted(
        [{"kind": k, **v} for k, v in by_kind.items()],
        key=lambda r: r["minutes"],
        reverse=True,
    )

    return {
        "days": days,
        "sessions": items[:60],
        "summary_28d": summary,
    }


@router.get("/training/muscle-balance")
async def training_muscle_balance(weeks: int = Query(4, gt=0, le=52)) -> dict:
    """Per-muscle-group set + volume breakdown over the last N weeks.

    Used for spotting imbalances (push/pull, lower neglect) and weekly volume targets.
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ws.exercise,
                   COUNT(*) AS sets,
                   SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE
              AND started_at::DATE >= (current_date - ($w * INTERVAL '7 days'))
            GROUP BY ws.exercise
            """,
            {"w": weeks},
        ).fetchall()
    finally:
        conn.close()

    buckets: dict[str, dict] = {
        g: {"sets": 0, "volume_kg": 0.0}
        for g in ("push", "pull", "legs", "core", "other")
    }
    for ex, sets_, vol in rows:
        g = _muscle_group(ex)
        buckets[g]["sets"] += int(sets_ or 0)
        buckets[g]["volume_kg"] += float(vol or 0)

    total_sets = sum(b["sets"] for b in buckets.values()) or 1
    out = [
        {
            "group": g,
            "sets": b["sets"],
            "volume_kg": round(b["volume_kg"], 1),
            "share_pct": round(b["sets"] * 100 / total_sets, 1),
            "weekly_sets": round(b["sets"] / weeks, 1),
        }
        for g, b in buckets.items()
    ]
    out.sort(key=lambda r: r["sets"], reverse=True)
    return {"weeks": weeks, "groups": out, "total_sets": total_sets}


@router.get("/insights/correlations")
async def insights_correlations() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                j.question,
                COUNT(*) AS sample_days,
                AVG(CASE WHEN j.answered_yes THEN r.score END) AS avg_recovery_yes,
                AVG(CASE WHEN NOT j.answered_yes THEN r.score END) AS avg_recovery_no,
                AVG(CASE WHEN j.answered_yes THEN r.hrv END) AS avg_hrv_yes,
                AVG(CASE WHEN NOT j.answered_yes THEN r.hrv END) AS avg_hrv_no
            FROM whoop_journal j
            JOIN recovery r ON r.date = j.date::DATE
            GROUP BY j.question
            HAVING COUNT(*) >= 10
            ORDER BY ABS(
                AVG(CASE WHEN j.answered_yes THEN r.hrv END) -
                AVG(CASE WHEN NOT j.answered_yes THEN r.hrv END)
            ) DESC NULLS LAST
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "question": r[0],
            "sample_days": r[1],
            "avg_recovery_yes": round(r[2], 1) if r[2] else None,
            "avg_recovery_no": round(r[3], 1) if r[3] else None,
            "avg_hrv_yes": round(r[4], 2) if r[4] else None,
            "avg_hrv_no": round(r[5], 2) if r[5] else None,
            "hrv_delta": round(r[4] - r[5], 2) if (r[4] and r[5]) else None,
        }
        for r in rows
    ]


class MedicationIn(BaseModel):
    name: str
    dose: str | None = None
    frequency: str | None = None


@router.post("/clinical/medication")
async def add_medication(body: MedicationIn) -> dict:
    """Add an active medication. Used to bootstrap the medications table so
    the dashboard's beta-blocker awareness works."""
    import uuid
    async with write_ctx() as conn:
        conn.execute(
            "INSERT INTO medications (id, name, dose, frequency, started) VALUES ($id, $n, $d, $f, current_date)",
            {"id": str(uuid.uuid4()), "n": body.name, "d": body.dose, "f": body.frequency},
        )
    return {"status": "ok", "name": body.name}


@router.get("/clinical/overview")
async def clinical_overview() -> dict:
    conn = get_read_conn()
    try:
        conditions = conn.execute(
            "SELECT name, onset, status FROM conditions WHERE valid_to IS NULL ORDER BY onset DESC"
        ).fetchall()
        medications = conn.execute(
            "SELECT name, dose, frequency, started FROM medications WHERE valid_to IS NULL ORDER BY started DESC"
        ).fetchall()
        key_labs = conn.execute(
            """
            SELECT DISTINCT ON (name) name, value, unit, collected_at
            FROM labs
            WHERE value IS NOT NULL
            ORDER BY name, collected_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return {
        "conditions": [{"name": r[0], "onset": str(r[1]) if r[1] else None, "status": r[2]} for r in conditions],
        "medications": [{"name": r[0], "dose": r[1], "frequency": r[2], "started": str(r[3]) if r[3] else None} for r in medications],
        "key_labs": [{"name": r[0], "value": round(r[1], 2), "unit": r[2], "collected_at": str(r[3]) if r[3] else None} for r in key_labs],
    }


@router.get("/body/trend")
async def body_trend() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS kg
            FROM measurements
            WHERE metric = 'body_mass_kg'
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "kg": round(r[1], 2), "lbs": round(r[1] * 2.20462, 1)} for r in rows]


@router.get("/body/vo2max")
async def body_vo2max() -> list[dict]:
    """Estimate VO2 max from WHOOP RHR using the Uth-Sørensen formula.

    VO2max ≈ 15.3 × HRmax / HRrest  (Uth et al., 2004)
    HRmax = 220 − 39 (Rob's age) = 181 bpm.
    Note: propranolol PRN blunts HRmax → treat values as floor estimates
    on days the beta-blocker was taken.
    """
    HR_MAX = 181  # 220 - 39
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT date, AVG(rhr) AS rhr
            FROM recovery
            WHERE rhr IS NOT NULL AND rhr > 30
            GROUP BY date
            ORDER BY date
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": str(r[0]), "vo2max": round(15.3 * HR_MAX / r[1], 1)}
        for r in rows
        if r[1]
    ]


@router.get("/whoop/patterns")
async def whoop_patterns() -> dict:
    """Recovery patterns derived from WHOOP data: day-of-week, distributions, correlations."""
    conn = get_read_conn()
    try:
        # Day-of-week average recovery (0=Mon … 6=Sun)
        dow_rows = conn.execute(
            """
            SELECT dayofweek(date) AS dow, AVG(score) AS avg_score, COUNT(*) AS n
            FROM recovery
            WHERE score IS NOT NULL
            GROUP BY dow
            ORDER BY dow
            """
        ).fetchall()

        # Recovery score distribution
        dist_rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN score < 34 THEN 'Red (0–33)'
                    WHEN score < 67 THEN 'Yellow (34–66)'
                    ELSE 'Green (67–100)'
                END AS bucket,
                COUNT(*) AS n
            FROM recovery
            WHERE score IS NOT NULL
            GROUP BY bucket
            """
        ).fetchall()

        # Sleep vs recovery scatter (90d)
        scatter_rows = conn.execute(
            """
            SELECT
                r.date,
                r.score AS recovery,
                r.hrv,
                r.rhr,
                (EPOCH(sl.ts_out) - EPOCH(sl.ts_in)) / 3600.0 AS sleep_h
            FROM recovery r
            JOIN sleep sl ON sl.night_date = r.date
            WHERE r.score IS NOT NULL
              AND sl.ts_in IS NOT NULL AND sl.ts_out IS NOT NULL
              AND r.date >= current_date - INTERVAL 90 DAY
            ORDER BY r.date DESC
            LIMIT 90
            """
        ).fetchall()

        # Rolling 7d average for trend
        trend_rows = conn.execute(
            """
            SELECT date, score, hrv, rhr
            FROM recovery
            WHERE score IS NOT NULL
              AND date >= current_date - INTERVAL 90 DAY
            ORDER BY date
            """
        ).fetchall()

    finally:
        conn.close()

    DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "by_day_of_week": [
            {"day": DOW_LABELS[int(r[0]) % 7], "avg_recovery": round(r[1], 1), "n": r[2]}
            for r in dow_rows
        ],
        "distribution": [
            {"bucket": r[0], "n": r[1]}
            for r in dist_rows
        ],
        "sleep_vs_recovery": [
            {
                "date": str(r[0]),
                "recovery": round(r[1], 0),
                "hrv": round(r[2], 1) if r[2] else None,
                "rhr": r[3],
                "sleep_h": round(r[4], 2) if r[4] else None,
            }
            for r in scatter_rows
        ],
        "trend_90d": [
            {"date": str(r[0]), "recovery": r[1], "hrv": round(r[2], 1) if r[2] else None, "rhr": r[3]}
            for r in trend_rows
        ],
    }


@router.get("/body/steps")
async def body_steps(days: int = Query(90, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts::DATE AS day, SUM(value_num) AS steps
            FROM measurements
            WHERE metric = 'step_count' AND ts::DATE >= $since
            GROUP BY day
            ORDER BY day
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "steps": int(r[1] or 0)} for r in rows]


@router.get("/body/rhr-trend")
async def body_rhr_trend(days: int = Query(90, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        apple_rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS rhr
            FROM measurements
            WHERE metric = 'resting_heart_rate' AND ts::DATE >= $since
            GROUP BY day ORDER BY day
            """,
            {"since": since},
        ).fetchall()
        whoop_rows = conn.execute(
            "SELECT date, rhr FROM recovery WHERE date >= $since ORDER BY date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    apple_map = {str(r[0]): round(r[1], 1) for r in apple_rows}
    whoop_map = {str(r[0]): r[1] for r in whoop_rows}
    all_dates = sorted(set(apple_map) | set(whoop_map))
    return [
        {"date": d, "apple": apple_map.get(d), "whoop": whoop_map.get(d)}
        for d in all_dates
    ]


@router.get("/oauth/status")
async def oauth_status() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute("SELECT source, last_sync_at, needs_reauth FROM oauth_state").fetchall()
    finally:
        conn.close()
    return [{"source": r[0], "last_sync_at": str(r[1]), "needs_reauth": r[2]} for r in rows]


@router.get("/briefing")
async def get_briefing() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT briefing_date, generated_at, training_call, training_rationale,
                   readiness_headline, coaching_note, flags, priority_metric,
                   input_tokens, output_tokens, cache_read_tokens, cost_usd
            FROM ai_briefing
            ORDER BY briefing_date DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {
        "briefing_date": str(row[0]),
        "generated_at": str(row[1]),
        "training_call": row[2],
        "training_rationale": row[3],
        "readiness_headline": row[4],
        "coaching_note": row[5],
        "flags": json.loads(row[6]) if row[6] else [],
        "priority_metric": row[7],
        "tokens": {
            "input": row[8],
            "output": row[9],
            "cache_read": row[10],
        },
        "cost_usd": row[11],
    }


# ── Next Workout ─────────────────────────────────────────────────────────────

_PUSH = {
    "bench press", "chest press", "push press", "overhead press", "ohp", "incline press",
    "decline press", "shoulder press", "dumbbell press", "chest fly", "cable fly", "push-up",
    "dip", "lateral raise", "front raise", "tricep", "skull crusher", "close grip bench",
    "pushdown", "overhead extension",
}
_PULL = {
    "row", "pull-up", "pullup", "chin-up", "chinup", "lat pulldown", "cable row", "face pull",
    "rear delt", "shrug", "deadlift", "rdl", "rack pull", "curl", "hammer curl", "preacher",
    "concentration curl", "reverse curl",
}
_LEGS = {
    "squat", "leg press", "lunge", "split squat", "bulgarian", "step-up", "hip thrust",
    "glute bridge", "leg curl", "leg extension", "calf raise", "hack squat", "goblet squat",
    "romanian deadlift", "sumo deadlift",
}
_CORE = {"plank", "crunch", "sit-up", "ab wheel", "pallof", "wood chop", "dead bug", "bird dog"}


def _muscle_group(exercise: str) -> str:
    e = exercise.lower()
    if any(k in e for k in _LEGS):
        return "legs"
    if any(k in e for k in _PUSH):
        return "push"
    if any(k in e for k in _PULL):
        return "pull"
    if any(k in e for k in _CORE):
        return "core"
    return "other"


_WORKOUT_CACHE: dict[str, dict] = {}

# kept for reference by the Ollama fallback path only
_PLAN_SCHEMA = {
    "type": "object",
    "required": ["readiness_tier", "readiness_summary", "recommendation", "warmup", "blocks", "cooldown", "clinical_notes", "vault_insights"],
    "properties": {
        "readiness_tier": {"type": "string", "enum": ["green", "yellow", "red"]},
        "readiness_summary": {"type": "string"},
        "recommendation": {
            "type": "object",
            "required": ["intensity", "focus", "rationale", "estimated_duration_min", "target_rpe"],
            "properties": {
                "intensity": {"type": "string", "enum": ["high", "moderate", "low", "rest"]},
                "focus": {"type": "string"},
                "rationale": {"type": "string"},
                "estimated_duration_min": {"type": "integer"},
                "target_rpe": {"type": "number"},
            },
        },
        "warmup": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "sets": {"type": "integer"},
                    "reps": {"type": "integer"},
                    "duration_sec": {"type": "integer"},
                    "notes": {"type": "string"},
                },
            },
        },
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "exercises"],
                "properties": {
                    "label": {"type": "string"},
                    "exercises": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "sets", "reps", "rpe_target"],
                            "properties": {
                                "name": {"type": "string"},
                                "sets": {"type": "integer"},
                                "reps": {"type": "string"},
                                "weight_kg": {"type": "number"},
                                "weight_lbs": {"type": "number"},
                                "rpe_target": {"type": "number"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "cooldown": {"type": "string"},
        "clinical_notes": {"type": "array", "items": {"type": "string"}},
        "vault_insights": {"type": "array", "items": {"type": "string"}},
    },
}

_WORKOUT_TOOL = {
    "type": "function",
    "function": {
        "name": "emit_workout_plan",
        "description": "Emit a structured workout plan for today.",
        "parameters": _PLAN_SCHEMA,
    },
}

_SYSTEM_PROMPT = """You are the user's personal strength + conditioning coach.

═══════════════════════════════════════════════════════════════
PROGRAMMING PHILOSOPHY (apply every plan)
═══════════════════════════════════════════════════════════════
• Strength priority: keep heavy compound work — that's what protects lean mass and drives the recomp.
• Fat-loss lever: density (shorter rest, supersets), metabolic finishers, and a Z2 conditioning piece on most non-deload days.
• Volume target: 10–15 working sets/muscle group/week; never sacrifice strength sets to chase calorie burn.
• Every plan should END with either (a) a 6–10 min metabolic finisher (kettlebell complex, sled push, bike intervals) on green/yellow days, OR (b) a Z2 walk/bike block on red/recovery days. This is the fat-burn engine.
• If recent push:pull or push:legs is imbalanced (see CONTEXT below), bias today toward the deficient group regardless of "most rested."
• If skin temp >+0.5°C above 28d baseline → recommend rest/Z2 only, flag illness possibility.
• If sleep <5h → cap intensity at moderate, no PR attempts.

═══════════════════════════════════════════════════════════════
CLINICAL CONTEXT (always factor in)
═══════════════════════════════════════════════════════════════
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
[clinical context loaded at runtime]

═══════════════════════════════════════════════════════════════
INTENSITY MATRIX (default; deviate only with reason)
═══════════════════════════════════════════════════════════════
GREEN (recovery ≥67, HRV ≥ −0.5σ):
  Primary: 4 sets × 4–6 reps @ working weight (RPE 8)
  Accessories: 3 × 8–12 (RPE 7); supersets allowed
  Finisher: 6–10 min metabolic complex (RPE 7–8)
  Total: 50–65 min

YELLOW (recovery 34–66, HRV −1.5 to −0.5σ):
  Primary: 3 × 6–8 @ ~85% working weight (RPE 7)
  Accessories: 3 × 10–12 (RPE 6)
  Finisher: 8–10 min Z2/Z3 bike or row (RPE 5–6)
  Total: 45–55 min

RED (recovery <34, HRV < −1.5σ, or sleep <5h):
  Primary: 2 × 8–10 @ 60–70% working weight (RPE 5)
  Accessories: skip OR 2 × 12–15 light isolation
  Finisher: 15–25 min Z2 walk/bike/row (RPE 3–4)
  Total: 30–45 min — recovery work, not training stimulus

═══════════════════════════════════════════════════════════════
SUPERSET / DENSITY GUIDANCE (fat-loss layer)
═══════════════════════════════════════════════════════════════
• On green/yellow days, pair antagonist accessory exercises (e.g. row + press, curl + tricep) with 60s rest — this raises calorie burn ~25% vs straight sets without hurting strength.
• Encode supersets as two consecutive exercises in the same block with notes: "Superset with previous — 60s rest after pair."
• Primary compound lifts get full 2–3 min rest. Don't superset the strength work.

═══════════════════════════════════════════════════════════════
FOR EVERY EXERCISE
═══════════════════════════════════════════════════════════════
• Pull the name VERBATIM from Rob's recent Hevy history (see TOP EXERCISES in context). Do not invent generic names.
• Prescribe weight in lbs, rounded to 5 lbs, derived from his working_weight × intensity %.
• Notes: 1 short cue (form/tempo) — not a paragraph.

═══════════════════════════════════════════════════════════════
OUTPUT
═══════════════════════════════════════════════════════════════
Respond with ONLY valid JSON — no markdown, no explanation, no code fences.
Top-level keys (exactly):
  readiness_tier: "green"|"yellow"|"red"
  readiness_summary: 1–2 sentence read of today's body
  recommendation: {intensity, focus, rationale (2 sentences MAX, cite numbers), estimated_duration_min, target_rpe}
  warmup: [{name, sets?, reps?, duration_sec?, notes?}]
  blocks: [{label, exercises:[{name, sets, reps, weight_lbs?, rpe_target, notes?}]}]
  cooldown: string
  clinical_notes: array of strings (cite any active medications or conditions relevant to today's plan)
  vault_insights: array of strings (cite specific research from context)

The plan should feel like it came from a coach who has read every data point — strain, HRV trend, push:pull ratio, body weight, last 5 sessions, cardio mix — and is solving the recomp problem with the data."""


@router.post("/workout/generate")
async def workout_generate() -> dict:
    """Generate today's workout plan via Claude (Anthropic API).

    Pipeline:
      1. Build live training context from DB (recovery, HRV, cardio, balance, etc.)
      2. Send to Claude Opus with the strength + fat-loss system prompt
      3. Parse JSON response, validate, persist, return
    """
    import anthropic
    from shc.config import settings

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured — falling back to /workout/next stub",
        )

    conn = get_read_conn()
    try:
        context = build_training_context(conn)
    finally:
        conn.close()

    user_prompt = (
        "Generate today's workout plan as JSON only. Use the live data below to "
        "make every prescription specific (real exercise names, real lbs, real RPE).\n\n"
        f"{context}"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        log.exception("Claude generation failed")
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc

    # Extract JSON from response. Be tolerant of code-fence stripping.
    raw = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Claude returned non-JSON: %s", raw[:300])
        raise HTTPException(status_code=502, detail=f"Claude returned non-JSON: {exc}") from exc

    try:
        validate_plan(plan)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid plan: {exc}") from exc

    today = date.today().isoformat()
    plan_with_meta = {
        "generated_at": today,
        "source": "claude",
        **plan,
    }
    await save_plan(plan_with_meta, source="claude")
    _WORKOUT_CACHE[today] = plan_with_meta

    # Log the LLM call for telemetry.
    try:
        await _log_llm_call(
            request_id=f"workout-{today}",
            model="claude-opus-4-7",
            route_reason="workout_generate",
            usage=response.usage,
        )
    except Exception:
        pass

    return plan_with_meta


@router.get("/workout/context")
async def workout_context() -> dict:
    """Return the full training context string used to generate workout plans.

    Call this from the Claude chat interface before generating a plan.
    """
    conn = get_read_conn()
    try:
        context = build_training_context(conn)
    finally:
        conn.close()
    return {"context": context}


@router.post("/workout/plan")
async def submit_workout_plan(body: WorkoutPlanSubmission) -> dict:
    """Accept a Claude-generated workout plan, validate it, persist it, and
    optionally push it to Hevy as a routine.

    This endpoint is the write-path used by the Claude chat interface.
    """
    try:
        validate_plan(body.plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    today = date.today().isoformat()
    plan_with_meta = {"generated_at": today, "source": body.source, **body.plan}

    await save_plan(plan_with_meta, source=body.source)
    _WORKOUT_CACHE[today] = plan_with_meta

    hevy_result = None
    if body.push_to_hevy:
        from shc.ingest.hevy import push_routine
        hevy_result = await push_routine(plan_with_meta)

    return {"status": "ok", "date": today, "hevy": hevy_result}


@router.delete("/workout/plan")
async def delete_workout_plan(target_date: str | None = Query(default=None)) -> dict:
    """Delete a stored workout plan (defaults to today). Used to discard test/bad plans."""
    d = target_date or date.today().isoformat()
    async with write_ctx() as conn:
        conn.execute("DELETE FROM workout_plans WHERE date = $d", {"d": d})
    _WORKOUT_CACHE.pop(d, None)
    return {"status": "ok", "date": d}


@router.get("/workout/next")
async def workout_next(regen: bool = Query(default=False)) -> dict:
    """Return today's workout plan.

    Priority order:
    1. In-memory cache (fast path, same process lifetime)
    2. DB-persisted plan for today (survives restarts)
    3. Fallback stub (instructs user to generate via chat)
    """
    today = date.today().isoformat()

    if not regen and today in _WORKOUT_CACHE:
        return _WORKOUT_CACHE[today]

    stored = load_plan(today)
    if stored and not regen:
        _WORKOUT_CACHE[today] = stored
        return stored

    # No plan yet — return a stub that prompts the user to generate via chat
    conn = get_read_conn()
    try:
        rec = conn.execute(
            "SELECT date, score, hrv, rhr FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()
        hrv_base = conn.execute(
            "SELECT hrv, hrv_28d_avg, hrv_28d_sd FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
        ).fetchone()
        sleep_row = conn.execute(
            "SELECT epoch(ts_out - ts_in) / 3600.0 FROM sleep ORDER BY night_date DESC LIMIT 1"
        ).fetchone()
        workout_rows = conn.execute(
            """
            SELECT w.started_at::DATE AS day, ws.exercise, COUNT(*) AS sets
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.is_warmup = FALSE AND w.started_at::DATE >= $since
            GROUP BY day, ws.exercise ORDER BY day DESC
            """,
            {"since": (date.today() - timedelta(days=14)).isoformat()},
        ).fetchall()
        scores_7 = conn.execute(
            "SELECT AVG(score) FROM recovery WHERE date >= $s",
            {"s": (date.today() - timedelta(days=7)).isoformat()},
        ).fetchone()
        scores_28 = conn.execute(
            "SELECT AVG(score) FROM recovery WHERE date >= $s",
            {"s": (date.today() - timedelta(days=28)).isoformat()},
        ).fetchone()
    finally:
        conn.close()

    rec_score = rec[1] if rec else None
    hrv_today = hrv_base[0] if hrv_base else None
    hrv_avg = hrv_base[1] if hrv_base else None
    hrv_sd = hrv_base[2] if hrv_base else None
    hrv_sigma = round((hrv_today - hrv_avg) / hrv_sd, 2) if (hrv_today and hrv_avg and hrv_sd) else None
    sleep_hours = round(float(sleep_row[0]), 1) if sleep_row and sleep_row[0] else None
    acwr_acute = float(scores_7[0]) if scores_7 and scores_7[0] else None
    acwr_chronic = float(scores_28[0]) if scores_28 and scores_28[0] else None
    acwr = round(acwr_acute / acwr_chronic, 2) if (acwr_acute and acwr_chronic) else None

    group_last_day: dict[str, str] = {}
    for row in workout_rows:
        g = _muscle_group(row[1])
        if g not in group_last_day or row[0] > date.fromisoformat(str(group_last_day[g])):
            group_last_day[g] = str(row[0])
    days_since: dict[str, int] = {
        g: (date.today() - date.fromisoformat(last)).days
        for g, last in group_last_day.items()
    }

    return _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today)


async def _log_llm_call(*, request_id: str, model: str, route_reason: str, usage) -> None:
    try:
        # OpenAI usage: prompt_tokens / completion_tokens; Anthropic: input_tokens / output_tokens
        input_tok = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
        output_tok = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
        async with write_ctx() as conn:
            conn.execute(
                "INSERT INTO llm_calls (ts, request_id, model, route_reason, input_tok, output_tok, cached_tok) VALUES (now(), $1, $2, $3, $4, $5, 0)",
                [request_id, model, route_reason, input_tok, output_tok],
            )
    except Exception as exc:
        log.warning("Failed to log LLM call: %s", exc)


def _select_exercises_for_focus(focus_group: str, n: int) -> list[tuple[str, float]]:
    """Pick `n` real exercises from working_weights for the given muscle group,
    prioritizing recently-performed compound movements. Returns (name, weight_kg).
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ww.exercise, ww.weight_kg, MAX(w.started_at::DATE) AS last_day, COUNT(*) AS sessions
            FROM working_weights ww
            JOIN workout_sets ws ON ws.exercise = ww.exercise
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.started_at::DATE >= (current_date - INTERVAL '120 days')
              AND ws.is_warmup = FALSE
            GROUP BY ww.exercise, ww.weight_kg
            ORDER BY last_day DESC, sessions DESC
            """
        ).fetchall()
    finally:
        conn.close()

    picked: list[tuple[str, float]] = []
    seen_keys: set[str] = set()
    for ex, wkg, _last, _n in rows:
        if _muscle_group(ex) != focus_group:
            continue
        # de-dup near-identical movement variants ("Bicep Curl (Cable)" vs "Cable Bicep Curl")
        key = "".join(c for c in ex.lower() if c.isalpha())[:14]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        picked.append((ex, float(wkg)))
        if len(picked) >= n:
            break
    return picked


def _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today) -> dict:
    tier = "green"
    if rec_score is not None:
        if rec_score < 34:
            tier = "red"
        elif rec_score < 67:
            tier = "yellow"
    most_rested = max(days_since.items(), key=lambda x: x[1]) if days_since else ("legs", 3)
    focus_group = most_rested[0]
    focus_map = {
        "legs": "Lower Body — Strength",
        "push": "Upper Body Push",
        "pull": "Upper Body Pull",
        "other": "Full Body",
        "core": "Full Body",
    }
    focus = focus_map.get(focus_group, "Full Body")
    intensity = "high" if tier == "green" else ("moderate" if tier == "yellow" else "low")
    rpe = 8.0 if tier == "green" else (6.5 if tier == "yellow" else 5.0)

    # Per-tier prescription: red = strict deload, yellow = moderate, green = working set %.
    weight_pct = 1.00 if tier == "green" else (0.85 if tier == "yellow" else 0.65)
    sets, reps_str = (4, "5") if tier == "green" else ((3, "8") if tier == "yellow" else (2, "10"))
    accessory_sets = sets - 1 if sets > 2 else sets

    primary = _select_exercises_for_focus(focus_group, 2)
    accessories = _select_exercises_for_focus(focus_group, 5)[2:5]  # different from primary

    def to_exercise(name: str, wkg: float, ssets: int, sreps: str, srpe: float, note: str) -> dict:
        scaled_lbs = round(wkg * weight_pct * 2.20462 / 5) * 5  # round to nearest 5 lbs
        return {
            "name": name,
            "sets": ssets,
            "reps": sreps,
            "weight_lbs": scaled_lbs if scaled_lbs > 0 else None,
            "rpe_target": srpe,
            "notes": note,
        }

    blocks: list[dict] = []
    if primary:
        blocks.append({
            "label": "Primary — Compound",
            "exercises": [
                to_exercise(
                    name, wkg, sets, reps_str, rpe,
                    f"~{int(weight_pct*100)}% of working weight ({round(wkg * 2.20462)} lbs)" if tier != "green" else "Working weight",
                )
                for name, wkg in primary
            ],
        })
    if accessories:
        blocks.append({
            "label": "Accessory",
            "exercises": [
                to_exercise(
                    name, wkg, accessory_sets, "10–12" if tier != "red" else "12–15", max(5.0, rpe - 1),
                    "Slow eccentric, full ROM",
                )
                for name, wkg in accessories
            ],
        })
    if not blocks:
        # Cold-start guard: no working weights yet for this group.
        blocks = [{
            "label": "Primary",
            "exercises": [{
                "name": f"{focus} compound (your choice)",
                "sets": sets,
                "reps": reps_str,
                "rpe_target": rpe,
                "notes": "No working weight on file for this group yet — pick a movement and log a set.",
            }],
        }]

    # ── Conditioning / metabolic finisher (fat-loss layer) ──
    # Avoids high-impact options because of forefoot overload + gait asymmetry.
    if tier == "green":
        blocks.append({
            "label": "Metabolic Finisher",
            "exercises": [
                {
                    "name": "Kettlebell Swing",
                    "sets": 5,
                    "reps": "20",
                    "weight_lbs": 53,
                    "rpe_target": 8.0,
                    "notes": "EMOM 5 min, 60s rest. Drive with hips.",
                },
                {
                    "name": "Sled Push",
                    "sets": 4,
                    "reps": "20m",
                    "rpe_target": 8.0,
                    "notes": "Heavy. Walk back. ~6 min.",
                },
            ],
        })
    elif tier == "yellow":
        blocks.append({
            "label": "Conditioning · Z2/Z3",
            "exercises": [
                {
                    "name": "Bike (upright or recumbent)",
                    "sets": 1,
                    "reps": "10 min",
                    "rpe_target": 6.0,
                    "notes": "Steady tempo. Use RPE 6 as intensity guide.",
                },
            ],
        })
    else:  # red
        blocks.append({
            "label": "Active Recovery · Zone 2",
            "exercises": [
                {
                    "name": "Walk or easy bike",
                    "sets": 1,
                    "reps": "20 min",
                    "rpe_target": 3.0,
                    "notes": "Conversational pace. Builds aerobic base without taxing recovery.",
                },
            ],
        })

    rationale = (
        f"{focus_group.capitalize()} last trained {most_rested[1]} days ago — most recovered."
        if days_since
        else "No recent training history — full body recommended."
    )
    if tier == "red":
        rationale += " Recovery low → working at 65% to preserve adaptation without taxing the system."
    elif tier == "yellow":
        rationale += " Moderate effort, 85% of working weights."

    return {
        "generated_at": today,
        "source": "fallback",
        "readiness_tier": tier,
        "readiness_summary": (
            (f"Recovery score {rec_score:.0f}." if rec_score else "No recovery data.")
            + (f" HRV {hrv_sigma:+.1f}σ from baseline." if hrv_sigma else "")
            + (f" Sleep {sleep_hours}h." if sleep_hours else "")
        ),
        "recommendation": {
            "intensity": intensity,
            "focus": focus,
            "rationale": rationale,
            "estimated_duration_min": 55 if tier != "red" else 35,
            "target_rpe": rpe,
        },
        "warmup": [
            {"name": "Joint circles (neck → ankles)", "duration_sec": 120},
            {"name": "Bodyweight squats", "sets": 2, "reps": 15, "notes": "Focus on depth"},
            {"name": f"{focus_group.capitalize()}-specific activation", "sets": 2, "reps": 12, "notes": "50% of working weight"},
        ],
        "blocks": blocks,
        "cooldown": "5 min mobility — target trained muscle groups",
        "clinical_notes": [
            [removed],
            [removed],
        ],
        "vault_insights": [
            "ACWR 0.8–1.3 minimizes injury risk (Gabbett, 2016) — current: " + (f"{acwr:.2f}" if acwr else "unknown"),
            "HRV-guided training outperforms fixed-load programs (Kiviniemi et al.)",
            f"{int(weight_pct*100)}% of working weight at {sets}×{reps_str} matches DUP {tier} day prescription.",
        ],
    }


# ── Briefing ──────────────────────────────────────────────────────────────────

@router.get("/briefing/context")
async def briefing_context() -> dict:
    """Return today's health snapshot for use when generating the daily briefing."""
    conn = get_read_conn()
    try:
        context = build_daily_context(conn)
    finally:
        conn.close()
    return {"context": context}


@router.post("/briefing")
async def submit_briefing(body: BriefingSubmission) -> dict:
    """Accept a Claude-generated daily briefing and persist it."""
    valid_calls = {"Push", "Train", "Maintain", "Easy", "Rest"}
    if body.training_call not in valid_calls:
        raise HTTPException(status_code=422, detail=f"training_call must be one of {valid_calls}")
    await store_briefing(body.model_dump())
    return {"status": "ok"}


# ── Lift progression ──────────────────────────────────────────────────────────

@router.get("/training/progression")
async def lift_progression(
    exercise: str = Query(..., description="Exercise name (partial match ok)"),
    sessions: int = Query(default=20, gt=0, le=100),
) -> dict:
    """Return per-session weight/volume history for a specific exercise."""
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                w.started_at::DATE AS day,
                ws.exercise,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup) AS work_sets,
                MAX(ws.weight_kg) FILTER (WHERE NOT ws.is_warmup) AS max_kg,
                SUM(ws.reps) FILTER (WHERE NOT ws.is_warmup) AS total_reps,
                SUM(ws.weight_kg * ws.reps) FILTER (WHERE NOT ws.is_warmup) AS volume_kg,
                AVG(ws.rpe) FILTER (WHERE NOT ws.is_warmup AND ws.rpe IS NOT NULL) AS avg_rpe
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE LOWER(ws.exercise) LIKE $pat
            GROUP BY day, ws.exercise
            ORDER BY day DESC
            LIMIT $n
            """,
            {"pat": f"%{exercise.lower()}%", "n": sessions},
        ).fetchall()
    finally:
        conn.close()

    history = [
        {
            "date": str(r[0]),
            "exercise": r[1],
            "work_sets": r[2],
            "max_lbs": round(r[3] * 2.20462, 1) if r[3] else None,
            "max_kg": round(r[3], 2) if r[3] else None,
            "total_reps": r[4],
            "volume_kg": round(r[5], 1) if r[5] else None,
            "avg_rpe": round(r[6], 1) if r[6] else None,
        }
        for r in rows
    ]

    # Progression signal: compare last 3 vs prior 3 max weights
    weights = [h["max_kg"] for h in history if h["max_kg"]]
    signal = None
    if len(weights) >= 6:
        recent = sum(weights[:3]) / 3
        prior = sum(weights[3:6]) / 3
        pct = (recent - prior) / prior * 100 if prior > 0 else 0
        signal = "progressing" if pct > 2 else ("stalled" if pct > -2 else "regressing")

    return {"exercise": exercise, "history": history, "progression_signal": signal}


@router.get("/training/stalls")
async def lift_stalls(min_sessions: int = Query(default=4, ge=2, le=20)) -> list[dict]:
    """Return exercises with no meaningful weight increase over the last N sessions."""
    conn = get_read_conn()
    try:
        # Get last N sessions per exercise with their max weight
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    ws.exercise,
                    w.started_at::DATE AS day,
                    MAX(ws.weight_kg) AS max_kg,
                    ROW_NUMBER() OVER (PARTITION BY ws.exercise ORDER BY w.started_at DESC) AS rn,
                    COUNT(*) OVER (PARTITION BY ws.exercise) AS total_sessions
                FROM workout_sets ws
                JOIN workouts w ON w.id = ws.workout_id
                WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL AND ws.weight_kg > 0
                GROUP BY ws.exercise, day, w.started_at
            )
            SELECT exercise, max_kg, rn, total_sessions
            FROM ranked
            WHERE rn <= $n AND total_sessions >= $n
            ORDER BY exercise, rn
            """,
            {"n": min_sessions},
        ).fetchall()
    finally:
        conn.close()

    # Group by exercise and check for stall
    from itertools import groupby
    stalls = []
    for exercise, group in groupby(rows, key=lambda r: r[0]):
        sessions = list(group)
        weights = [r[1] for r in sessions if r[1]]
        total = sessions[0][3] if sessions else 0
        if len(weights) < min_sessions:
            continue
        mn, mx = min(weights), max(weights)
        variation = (mx - mn) / mn if mn > 0 else 0
        if variation < 0.02:  # < 2% change = stalled
            stalls.append({
                "exercise": exercise,
                "min_kg": round(mn, 2),
                "max_kg": round(mx, 2),
                "min_lbs": round(mn * 2.20462, 1),
                "max_lbs": round(mx * 2.20462, 1),
                "sessions_checked": min_sessions,
                "total_sessions_on_record": total,
            })

    stalls.sort(key=lambda x: -x["total_sessions_on_record"])
    return stalls


# ── Workout retrospective ─────────────────────────────────────────────────────

@router.get("/workout/recent")
async def recent_workouts(limit: int = Query(default=10, gt=0, le=50)) -> list[dict]:
    """Return recent workouts with their exercise summary — for retrospective generation."""
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                w.id,
                w.started_at,
                w.ended_at,
                w.notes,
                STRING_AGG(DISTINCT ws.exercise, ', ') AS exercises,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup) AS work_sets,
                MAX(ws.weight_kg) AS max_weight_kg,
                SUM(ws.weight_kg * ws.reps) FILTER (WHERE NOT ws.is_warmup) AS volume_kg,
                AVG(ws.rpe) FILTER (WHERE ws.rpe IS NOT NULL) AS avg_rpe
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            GROUP BY w.id, w.started_at, w.ended_at, w.notes
            ORDER BY w.started_at DESC
            LIMIT $n
            """,
            {"n": limit},
        ).fetchall()
        # Fetch which ones already have a retrospective
        retro_ids = {
            r[0]
            for r in conn.execute("SELECT workout_id FROM workout_retrospectives").fetchall()
        }
    finally:
        conn.close()

    return [
        {
            "id": r[0],
            "started_at": str(r[1]),
            "ended_at": str(r[2]) if r[2] else None,
            "notes": r[3],
            "exercises": r[4],
            "work_sets": r[5],
            "volume_kg": round(r[7], 1) if r[7] else None,
            "volume_lbs": round(r[7] * 2.20462, 1) if r[7] else None,
            "avg_rpe": round(r[8], 1) if r[8] else None,
            "has_retrospective": r[0] in retro_ids,
        }
        for r in rows
    ]


@router.post("/workout/retrospective")
async def submit_retrospective(body: RetrospectiveSubmission) -> dict:
    """Store a Claude-generated workout retrospective."""
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO workout_retrospectives
                (workout_id, generated_at, summary, progressive_overload_achieved,
                 rpe_vs_target, flags, vault_insights)
            VALUES ($wid, now(), $summary, $po, $rpe, $flags, $vi)
            ON CONFLICT (workout_id) DO UPDATE SET
                generated_at = excluded.generated_at,
                summary = excluded.summary,
                progressive_overload_achieved = excluded.progressive_overload_achieved,
                rpe_vs_target = excluded.rpe_vs_target,
                flags = excluded.flags,
                vault_insights = excluded.vault_insights
            """,
            {
                "wid": body.workout_id,
                "summary": body.summary,
                "po": body.progressive_overload_achieved,
                "rpe": body.rpe_vs_target,
                "flags": json.dumps(body.flags),
                "vi": json.dumps(body.vault_insights),
            },
        )
    return {"status": "ok", "workout_id": body.workout_id}
