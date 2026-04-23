from __future__ import annotations

import json
import logging
import statistics
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query

from shc.config import settings
from shc.db.schema import get_read_conn

router = APIRouter(tags=["dashboard"])
log = logging.getLogger(__name__)


@router.get("/recovery/today")
async def recovery_today() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT date, score, hrv, rhr, skin_temp FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {"date": str(row[0]), "score": row[1], "hrv": row[2], "rhr": row[3], "skin_temp": row[4]}


@router.get("/recovery/trend")
async def recovery_trend(days: int = 14) -> list[dict]:
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
async def hrv_trend(days: int = 28) -> list[dict]:
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
async def sleep_recent(days: int = 7) -> list[dict]:
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
async def sleep_trend(days: int = 30) -> list[dict]:
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
        items.append(
            {
                "headline": f"Long sleep lifts HRV by {delta:+.1f}ms next day",
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
async def training_heatmap(weeks: int = 104) -> list[dict]:
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
async def training_weekly(weeks: int = 52) -> list[dict]:
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
async def training_prs(n: int = 15) -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT exercise, MAX(weight_kg) AS pr_kg, MAX(started_at::DATE) AS last_performed
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
            GROUP BY exercise
            HAVING COUNT(*) >= 5 AND STDDEV(weight_kg) > 2
            ORDER BY pr_kg DESC
            LIMIT $n
            """,
            {"n": n},
        ).fetchall()
    finally:
        conn.close()
    return [
        {"exercise": r[0], "pr_lbs": round(r[1] * 2.20462, 1), "pr_kg": round(r[1], 1), "last_performed": str(r[2])}
        for r in rows
    ]


@router.get("/training/top-exercises")
async def training_top_exercises(n: int = 10) -> list[dict]:
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
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS v
            FROM measurements
            WHERE metric = 'vo2_max'
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "vo2max": round(r[1], 1)} for r in rows]


@router.get("/body/steps")
async def body_steps(days: int = 90) -> list[dict]:
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
async def body_rhr_trend(days: int = 90) -> list[dict]:
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

_WORKOUT_TOOL = {
    "name": "emit_workout_plan",
    "description": "Emit a structured workout plan for today.",
    "input_schema": {
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
    },
}

_SYSTEM_PROMPT = """You are the user's personal strength + conditioning coach.

CLINICAL PROFILE — read before every plan:
• Lexapro 10mg daily (SSRI) → suppresses HRV; interpret HRV thresholds conservatively
• Propranolol PRN (as-needed for anxiety, beta blocker) → if taken, blunts HR response — use RPE not HR; strain metrics unreliable on propranolol days
• Asthma (Alvesco inhaler 2x/day) → use inhaler before hard sessions; monitor for wheeze at high intensity
• OSA, off CPAP since early 2026 → sleep quality matters more than raw hours
• Left shoulder fully resolved as of 04/2026 — no restrictions
• LDL 154 mg/dL (borderline), HbA1c 5.5% (normal) — metabolic health improving

TRAINING HISTORY:
• 9 years Fitbod data, 33,000+ sets, consistent compound lifter
• DUP periodization, goal: strength + body recomposition at 39

COACHING PRINCIPLES:
• Recovery >67 = green; ACWR 0.8–1.3 = safe zone; HRV within ±1σ = normal
• Sequence to respect 48-72h muscle group recovery
• Train most rested group when in doubt
• Compound movements, progressive overload, proper warm-up

Generate today's plan with emit_workout_plan. Name actual exercises from Rob's history, prescribe exact weights from working weight data, use RPE appropriate to today's readiness tier. Make it feel like it came from a coach who knows every data point about Rob."""


@router.get("/workout/next")
async def workout_next(regen: bool = Query(default=False)) -> dict:
    """AI-generated next workout plan using today's biometrics, training history, and clinical context."""
    today = date.today().isoformat()

    if not regen and today in _WORKOUT_CACHE:
        return _WORKOUT_CACHE[today]

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
            GROUP BY day, ws.exercise
            ORDER BY day DESC
            """,
            {"since": (date.today() - timedelta(days=14)).isoformat()},
        ).fetchall()
        ww_rows = conn.execute(
            "SELECT exercise, weight_kg FROM working_weights ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()
        pref_rows = conn.execute(
            "SELECT exercise, status, notes FROM exercise_preferences WHERE status IN ('no', 'sub')"
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

    days_since: dict[str, int] = {}
    for g, last in group_last_day.items():
        days_since[g] = (date.today() - date.fromisoformat(last)).days

    ww_lines = "\n".join(f"• {r[0]}: {round(r[1] * 2.20462, 1)} lbs" for r in ww_rows) if ww_rows else "No data — prescribe conservative starting weights"
    excl_lines = "\n".join(f"• {r[0]} ({r[1]})" for r in pref_rows) if pref_rows else "None"

    hrv_line = (
        f"{hrv_today:.1f}ms (baseline {hrv_avg:.1f}ms, σ {hrv_sigma:+.2f})"
        if (hrv_today and hrv_avg and hrv_sigma is not None) else "no data"
    )
    acwr_line = (
        f"{acwr} (acute {acwr_acute:.0f} / chronic {acwr_chronic:.0f})"
        if (acwr and acwr_acute and acwr_chronic) else "insufficient data"
    )
    mg_lines = "\n".join(f"• {g}: {d} days" for g, d in sorted(days_since.items(), key=lambda x: -x[1]))
    for g_name in ("legs", "push", "pull"):
        if g_name not in days_since:
            mg_lines += f"\n• {g_name}: not trained in past 14d"

    user_context = f"""TODAY: {today}

BIOMETRICS:
• Recovery score: {rec_score if rec_score is not None else 'no data'}
• HRV: {hrv_line}
• Sleep last night: {sleep_hours}h
• ACWR proxy: {acwr_line}

MUSCLE GROUP REST STATUS:
{mg_lines}

WORKING WEIGHTS:
{ww_lines}

EXERCISES TO AVOID/SUBSTITUTE:
{excl_lines}
"""

    if not settings.anthropic_api_key:
        return _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today)

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    request_id = str(uuid.uuid4())

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            tools=[_WORKOUT_TOOL],
            tool_choice={"type": "tool", "name": "emit_workout_plan"},
            messages=[{"role": "user", "content": user_context}],
        )
        plan = next(
            (b.input for b in response.content if b.type == "tool_use" and b.name == "emit_workout_plan"),
            None,
        )
        if plan is None:
            return _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today)

        _log_llm_call(request_id=request_id, model="claude-sonnet-4-6", route_reason="workout_next", usage=response.usage)
        result = {"generated_at": today, "source": "claude", **plan}
        _WORKOUT_CACHE[today] = result
        return result

    except Exception as exc:
        log.error("workout_next LLM call failed: %s", exc)
        return _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today)


def _log_llm_call(*, request_id: str, model: str, route_reason: str, usage) -> None:
    try:
        conn = get_read_conn()
        conn.execute(
            "INSERT INTO llm_calls (ts, request_id, model, route_reason, input_tok, output_tok, cached_tok) VALUES (now(), ?, ?, ?, ?, ?, ?)",
            [request_id, model, route_reason, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None), getattr(usage, "cache_read_input_tokens", 0)],
        )
        conn.close()
    except Exception as exc:
        log.warning("Failed to log LLM call: %s", exc)


def _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today) -> dict:
    tier = "green"
    if rec_score is not None:
        if rec_score < 34:
            tier = "red"
        elif rec_score < 67:
            tier = "yellow"
    most_rested = max(days_since.items(), key=lambda x: x[1]) if days_since else ("legs", 3)
    focus_map = {"legs": "Lower Body — Strength", "push": "Upper Body Push", "pull": "Upper Body Pull", "other": "Full Body", "core": "Full Body"}
    focus = focus_map.get(most_rested[0], "Full Body")
    intensity = "high" if tier == "green" else ("moderate" if tier == "yellow" else "low")
    rpe = 8.0 if tier == "green" else (6.5 if tier == "yellow" else 5.0)
    return {
        "generated_at": today,
        "source": "fallback",
        "readiness_tier": tier,
        "readiness_summary": (f"Recovery score {rec_score:.0f}." if rec_score else "No recovery data.") + (f" HRV {hrv_sigma:+.1f}σ from baseline." if hrv_sigma else "") + (f" Sleep {sleep_hours}h." if sleep_hours else ""),
        "recommendation": {"intensity": intensity, "focus": focus, "rationale": f"{most_rested[0].capitalize()} last trained {most_rested[1]} days ago — most recovered.", "estimated_duration_min": 55, "target_rpe": rpe},
        "warmup": [{"name": "Joint circles (neck → ankles)", "duration_sec": 120}, {"name": "Bodyweight squats", "sets": 2, "reps": 15, "notes": "Focus on depth"}],
        "blocks": [{"label": "Primary — Compound", "exercises": [{"name": "Work primary compound", "sets": 4, "reps": "5", "rpe_target": rpe, "notes": "Add Anthropic API key for exercise-specific prescription"}]}],
        "cooldown": "5 min mobility — target trained muscle groups",
        "clinical_notes": [[removed], [removed]],
        "vault_insights": ["ACWR 0.8–1.3 minimizes injury risk (Gabbett, 2016) — current: " + (f"{acwr:.2f}" if acwr else "unknown"), "HRV-guided training outperforms fixed-load programs (Kiviniemi et al.)"],
    }
