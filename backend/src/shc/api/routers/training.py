"""Training / mesocycle API endpoints.

GET  /api/training/mesocycle          → current mesocycle state + volume summary
GET  /api/training/progression        → per-exercise scores for recent exercises
POST /api/training/mesocycle/advance  → transition active → deloading → completed + new
POST /api/training/scores/recompute   → recompute all exercise scores for this week
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shc.db.schema import get_read_conn, write_ctx
from shc.training.mesocycle import (
    advance_mesocycle,
    compute_all_scores,
    ensure_active_mesocycle,
    mesocycle_context_block,
    score_exercise,
    volume_targets,
    weekly_e1rm,
)

router = APIRouter(tags=["training"])
log = logging.getLogger(__name__)


class AdvanceRequest(BaseModel):
    trigger: str = "manual"  # 'scheduled' | 'hrv_drop' | 'volume_cap' | 'manual'


@router.get("/training/mesocycle")
async def get_mesocycle() -> dict[str, Any]:
    conn = get_read_conn()
    try:
        state = ensure_active_mesocycle(conn)
        targets = volume_targets(conn, state.id)
        return {
            "id": state.id,
            "started_on": state.started_on.isoformat(),
            "planned_weeks": state.planned_weeks,
            "status": state.status,
            "week_number": state.week_number,
            "weeks_remaining": state.weeks_remaining,
            "is_deload_week": state.is_deload_week,
            "deload_trigger": state.deload_trigger,
            "notes": state.notes,
            "volume_targets": {
                mg: {"mev": t.mev, "mav": t.mav, "mrv": t.mrv} for mg, t in targets.items()
            },
        }
    finally:
        conn.close()


@router.get("/training/load-curve")
async def get_load_curve(days: int = 90) -> dict[str, Any]:
    """Banister fitness-fatigue model over the last N days.

    Returns per-day composite_load + CTL (42d EWMA, fitness), ATL (7d EWMA,
    fatigue), and TSB = CTL - ATL (form). Positive TSB = fresh, negative TSB
    = fatigued. Window of -10 to +5 is typical race-ready zone.
    """
    import math

    days = max(28, min(days, 365))
    conn = get_read_conn()
    try:
        # Pull a 60d warm-up so EWMAs at the start of the visible window are
        # initialised against real history, not zero.
        start = date.today() - timedelta(days=days + 60)
        rows = conn.execute(
            "SELECT date, COALESCE(composite_load, 0) "
            "FROM v_daily_load WHERE date >= ? ORDER BY date",
            [start.isoformat()],
        ).fetchall()
        if not rows:
            return {"as_of": date.today().isoformat(), "points": []}

        # Fill missing dates with 0 load so EWMAs decay correctly on rest days.
        by_date = {str(r[0]): float(r[1] or 0) for r in rows}
        first_date = date.fromisoformat(min(by_date.keys()))
        last_date = date.today()
        full: list[tuple[date, float]] = []
        d = first_date
        while d <= last_date:
            full.append((d, by_date.get(d.isoformat(), 0.0)))
            d = d + timedelta(days=1)

        # Banister EWMA: x_t = x_{t-1} * exp(-1/tau) + load_t * (1 - exp(-1/tau))
        ctl_tau, atl_tau = 42.0, 7.0
        ctl_decay = math.exp(-1.0 / ctl_tau)
        atl_decay = math.exp(-1.0 / atl_tau)
        ctl, atl = 0.0, 0.0
        points: list[dict[str, Any]] = []
        cutoff = last_date - timedelta(days=days)
        for d, load in full:
            ctl = ctl * ctl_decay + load * (1 - ctl_decay)
            atl = atl * atl_decay + load * (1 - atl_decay)
            if d >= cutoff:
                points.append(
                    {
                        "date": d.isoformat(),
                        "load": round(load, 2),
                        "ctl": round(ctl, 2),
                        "atl": round(atl, 2),
                        "tsb": round(ctl - atl, 2),
                    }
                )

        latest = points[-1] if points else None
        return {
            "as_of": last_date.isoformat(),
            "points": points,
            "today": latest,
            "tau": {"ctl_days": int(ctl_tau), "atl_days": int(atl_tau)},
        }
    finally:
        conn.close()


@router.get("/training/progression/all")
async def get_progression_all(weeks: int = 8) -> dict[str, Any]:
    """All-exercises e1RM + trend scores — used by goal scorecard.

    Same logic as get_progression but at a distinct path to avoid shadowing
    the dashboard.py per-exercise progression route.
    """
    conn = get_read_conn()
    try:
        cutoff = date.today() - timedelta(weeks=weeks)
        exercises = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT exercise
                FROM workout_sets_dedup
                WHERE started_at::DATE >= ?
                  AND weight_kg > 0 AND reps > 0
                ORDER BY exercise
                """,
                [cutoff],
            ).fetchall()
        ]
        results: list[dict[str, Any]] = []
        for ex in exercises:
            ps = score_exercise(conn, ex)
            if ps is None:
                history = weekly_e1rm(conn, ex, n_weeks=weeks)
                if history:
                    latest = history[-1]
                    results.append(
                        {
                            "exercise": ex,
                            "e1rm_lbs": round(latest.e1rm_kg * 2.20462),
                            "work_sets": latest.work_sets,
                            "perf_score": None,
                            "trend": None,
                            "recommendation": "insufficient history",
                        }
                    )
            else:
                results.append(
                    {
                        "exercise": ps.exercise,
                        "e1rm_lbs": round(ps.e1rm_lbs),
                        "work_sets": ps.work_sets,
                        "perf_score": ps.perf_score,
                        "trend": ps.trend,
                        "recommendation": ps.recommendation,
                    }
                )
        return {"exercises": results, "as_of": date.today().isoformat()}
    finally:
        conn.close()


@router.get("/training/progression")
async def get_progression(weeks: int = 4) -> dict[str, Any]:
    conn = get_read_conn()
    try:
        cutoff = date.today() - timedelta(weeks=weeks)
        exercises = [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT exercise_name
                FROM workout_sets_dedup
                WHERE started_at::DATE >= ?
                  AND weight_kg > 0 AND reps > 0
                ORDER BY exercise_name
                """,
                [cutoff],
            ).fetchall()
        ]

        results: list[dict[str, Any]] = []
        for ex in exercises:
            ps = score_exercise(conn, ex)
            if ps is None:
                history = weekly_e1rm(conn, ex, n_weeks=weeks)
                if history:
                    latest = history[-1]
                    results.append(
                        {
                            "exercise": ex,
                            "e1rm_lbs": round(latest.e1rm_kg * 2.20462),
                            "work_sets": latest.work_sets,
                            "perf_score": None,
                            "trend": None,
                            "recommendation": "insufficient history",
                        }
                    )
            else:
                results.append(
                    {
                        "exercise": ps.exercise,
                        "e1rm_lbs": round(ps.e1rm_lbs),
                        "work_sets": ps.work_sets,
                        "perf_score": ps.perf_score,
                        "trend": ps.trend,
                        "recommendation": ps.recommendation,
                    }
                )

        return {"exercises": results, "as_of": date.today().isoformat()}
    finally:
        conn.close()


@router.post("/training/mesocycle/advance")
async def post_advance(req: AdvanceRequest) -> dict[str, Any]:
    async with write_ctx() as conn:
        new_state = advance_mesocycle(conn, trigger=req.trigger)
    return {
        "status": new_state.status,
        "id": new_state.id,
        "started_on": new_state.started_on.isoformat(),
        "week_number": new_state.week_number,
    }


@router.post("/training/scores/recompute")
async def post_recompute() -> dict[str, Any]:
    async with write_ctx() as conn:
        compute_all_scores(conn)
    return {"ok": True, "message": "Scores recomputed for current week"}


@router.get("/training/context")
async def get_training_context() -> dict[str, str]:
    """Return the mesocycle context block that gets injected into workout planner prompts."""
    conn = get_read_conn()
    try:
        block = mesocycle_context_block(conn)
        return {"context": block}
    finally:
        conn.close()


@router.get("/training/muscle-volume")
async def get_muscle_volume() -> dict[str, Any]:
    """Per-muscle weekly set counts vs MEV/MAV/MRV targets from the active mesocycle.

    Joins workout_sets_dedup → exercise_muscle_map to group sets by muscle.
    Falls back gracefully if exercise_muscle_map is empty (returns empty muscles list).
    """
    conn = get_read_conn()
    try:
        # Current week Mon–Sun window
        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        state = ensure_active_mesocycle(conn)
        targets = volume_targets(conn, state.id)

        # Check if exercise_muscle_map table exists (created by migration 0025)
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'exercise_muscle_map'"
        ).fetchone()[0]

        muscles: list[dict[str, Any]] = []
        unmapped_exercises: list[str] = []

        if table_exists:
            rows = conn.execute(
                """
                SELECT
                    m.primary_muscle,
                    COUNT(DISTINCT ws.id) AS work_sets
                FROM workout_sets_dedup ws
                JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
                WHERE ws.started_at::DATE >= ?
                  AND NOT ws.is_warmup
                  AND ws.weight_kg > 0 AND ws.reps > 0
                GROUP BY m.primary_muscle
                ORDER BY m.primary_muscle
                """,
                [week_start.isoformat()],
            ).fetchall()
            muscle_sets = {r[0]: int(r[1]) for r in rows}

            # Find exercises in this week that lack a muscle mapping
            unmapped = conn.execute(
                """
                SELECT DISTINCT ws.exercise
                FROM workout_sets_dedup ws
                LEFT JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
                WHERE ws.started_at::DATE >= ?
                  AND NOT ws.is_warmup
                  AND ws.weight_kg > 0 AND ws.reps > 0
                  AND m.exercise_name IS NULL
                ORDER BY ws.exercise
                """,
                [week_start.isoformat()],
            ).fetchall()
            unmapped_exercises = [r[0] for r in unmapped]

            # All known muscles (union of mapped sets + target keys)
            all_muscles = sorted(set(muscle_sets.keys()) | set(targets.keys()))
            for muscle in all_muscles:
                t = targets.get(muscle)
                muscles.append(
                    {
                        "muscle": muscle,
                        "weekly_sets": muscle_sets.get(muscle, 0),
                        "mev": t.mev if t else None,
                        "mav": t.mav if t else None,
                        "mrv": t.mrv if t else None,
                    }
                )

        return {
            "as_of": today.isoformat(),
            "week_start": week_start.isoformat(),
            "mesocycle_id": state.id,
            "muscles": muscles,
            "unmapped_exercises": unmapped_exercises,
        }
    finally:
        conn.close()


@router.get("/pickleball/trend")
async def get_pickleball_trend(days: int = 90) -> dict[str, Any]:
    """Pickleball session history with recovery context.

    Returns session list, next-day HRV delta per session, play freshness
    (recovery score on play days), and tournament events.
    """
    conn = get_read_conn()
    try:
        since = (date.today() - timedelta(days=days)).isoformat()

        # Pickleball cardio sessions
        sessions = conn.execute(
            """
            SELECT cs.date, cs.duration_min, cs.avg_hr, cs.rpe,
                   r.score AS recovery_day_of,
                   r.hrv AS hrv_day_of,
                   r2.hrv AS hrv_next_day
            FROM cardio_sessions cs
            LEFT JOIN recovery r ON r.date = cs.date
            LEFT JOIN recovery r2 ON r2.date = cs.date + INTERVAL '1 day'
            WHERE cs.modality ILIKE '%pickleball%'
              AND cs.date >= ?
            ORDER BY cs.date DESC
            """,
            [since],
        ).fetchall()

        # HRV baseline for delta calculation
        hrv_baseline_row = conn.execute(
            "SELECT AVG(hrv) FROM recovery WHERE date >= ? AND hrv IS NOT NULL",
            [since],
        ).fetchone()
        hrv_baseline = (
            float(hrv_baseline_row[0]) if hrv_baseline_row and hrv_baseline_row[0] else None
        )

        session_list = []
        for r in sessions:
            hrv_delta = None
            if r[5] is not None and r[6] is not None:
                hrv_delta = round(r[6] - r[5], 1)
            session_list.append(
                {
                    "date": str(r[0]),
                    "duration_min": r[1],
                    "avg_hr": r[2],
                    "rpe": r[3],
                    "recovery_day_of": round(r[4], 0) if r[4] is not None else None,
                    "hrv_day_of": round(r[5], 1) if r[5] is not None else None,
                    "hrv_next_day": round(r[6], 1) if r[6] is not None else None,
                    "hrv_delta": hrv_delta,
                }
            )

        # Tournament events
        events_exist = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'tournament_events'"
        ).fetchone()[0]

        tournaments: list[dict[str, Any]] = []
        if events_exist:
            t_rows = conn.execute(
                "SELECT id, event_date, event_name, format, dupr_before, dupr_after, result_notes "
                "FROM tournament_events ORDER BY event_date DESC LIMIT 20"
            ).fetchall()
            tournaments = [
                {
                    "id": r[0],
                    "date": str(r[1]),
                    "name": r[2],
                    "format": r[3],
                    "dupr_before": r[4],
                    "dupr_after": r[5],
                    "dupr_delta": round(r[5] - r[4], 2)
                    if r[4] is not None and r[5] is not None
                    else None,
                    "result_notes": r[6],
                }
                for r in t_rows
            ]

        # Freshness summary: avg recovery on play days vs non-play days
        play_dates = {str(r[0]) for r in sessions}
        freshness = None
        if play_dates:
            avg_play_recovery = conn.execute(
                f"SELECT AVG(score) FROM recovery WHERE date IN ({','.join(['?' for _ in play_dates])})",
                list(play_dates),
            ).fetchone()
            freshness = (
                round(float(avg_play_recovery[0]), 1)
                if avg_play_recovery and avg_play_recovery[0]
                else None
            )

        return {
            "as_of": date.today().isoformat(),
            "sessions": session_list,
            "tournaments": tournaments,
            "hrv_baseline": hrv_baseline,
            "avg_recovery_on_play_days": freshness,
            "total_sessions": len(session_list),
            "total_duration_min": sum(s["duration_min"] or 0 for s in session_list),
        }
    finally:
        conn.close()


# DUPR doubles rating goal — Rob's 2026 target (4.5 → 5.0).
DUPR_TARGET_DOUBLES = 5.0


@router.get("/pickleball/dupr")
def dupr_rating() -> dict[str, Any]:
    """Return the DUPR rating snapshot series plus the current value and sync state."""
    conn = get_read_conn()
    try:
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'dupr_snapshots'"
        ).fetchone()[0]
        snapshots: list[dict[str, Any]] = []
        if table_exists:
            rows = conn.execute(
                "SELECT date, doubles, singles, doubles_provisional "
                "FROM dupr_snapshots ORDER BY date"
            ).fetchall()
            snapshots = [
                {
                    "date": str(r[0]),
                    "doubles": r[1],
                    "singles": r[2],
                    "doubles_provisional": r[3],
                }
                for r in rows
            ]
        state = conn.execute(
            "SELECT last_sync_at, needs_reauth FROM oauth_state WHERE source = 'dupr'"
        ).fetchone()
    finally:
        conn.close()

    current = snapshots[-1] if snapshots else None
    first_doubles = next((s["doubles"] for s in snapshots if s["doubles"] is not None), None)
    return {
        "as_of": date.today().isoformat(),
        "snapshots": snapshots,
        "current": current,
        "baseline_doubles": first_doubles,
        "target_doubles": DUPR_TARGET_DOUBLES,
        "last_sync_at": state[0] if state else None,
        "needs_reauth": bool(state[1]) if state else False,
    }


@router.post("/pickleball/dupr/sync")
async def dupr_sync() -> dict[str, Any]:
    """Pull the current DUPR rating and store today's snapshot."""
    from shc.ingest import dupr

    try:
        return await dupr.sync_rating()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"DUPR API error: {exc}") from exc


@router.post("/pickleball/dupr/sync-matches")
async def dupr_sync_matches() -> dict[str, Any]:
    """Pull full DUPR match history and upsert into dupr_matches."""
    from shc.ingest import dupr

    try:
        return await dupr.sync_matches()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"DUPR API error: {exc}") from exc


@router.get("/pickleball/matches")
def get_pickleball_matches() -> dict[str, Any]:
    """Return DUPR match history joined with WHOOP recovery on match days.

    Requires migration 0027 (dupr_matches table). Returns empty list gracefully
    if table doesn't exist yet.
    """
    conn = get_read_conn()
    try:
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'dupr_matches'"
        ).fetchone()[0]
        if not table_exists:
            return {"matches": [], "total": 0}

        rows = conn.execute(
            """
            SELECT
                m.match_id, m.event_date, m.event_name, m.venue, m.format,
                m.partner_name, m.opponent1_name, m.opponent2_name,
                m.won,
                m.game1_us, m.game1_them,
                m.game2_us, m.game2_them,
                m.game3_us, m.game3_them,
                m.dupr_pre, m.dupr_post, m.dupr_delta,
                r.score   AS recovery_score,
                r.hrv     AS hrv_ms,
                r.rhr     AS rhr_bpm
            FROM dupr_matches m
            LEFT JOIN recovery r ON r.date = m.event_date::DATE
            ORDER BY m.event_date DESC, m.match_id DESC
            """
        ).fetchall()

        matches = [
            {
                "match_id": r[0],
                "event_date": str(r[1]),
                "event_name": r[2],
                "venue": r[3],
                "format": r[4],
                "partner_name": r[5],
                "opponent1_name": r[6],
                "opponent2_name": r[7],
                "won": r[8],
                "games": [
                    {"us": r[9], "them": r[10]} if r[9] is not None else None,
                    {"us": r[11], "them": r[12]} if r[11] is not None else None,
                    {"us": r[13], "them": r[14]} if r[13] is not None else None,
                ],
                "dupr_pre": round(r[15], 3) if r[15] is not None else None,
                "dupr_post": round(r[16], 3) if r[16] is not None else None,
                "dupr_delta": round(r[17], 4) if r[17] is not None else None,
                "recovery_score": round(r[18], 0) if r[18] is not None else None,
                "hrv_ms": round(r[19], 1) if r[19] is not None else None,
                "rhr_bpm": r[20],
            }
            for r in rows
        ]

        return {"matches": matches, "total": len(matches)}
    finally:
        conn.close()
