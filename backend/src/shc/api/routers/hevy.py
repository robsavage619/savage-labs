from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn
from shc.ingest import hevy as hevy_ingest

log = logging.getLogger(__name__)

router = APIRouter(tags=["hevy"])


@router.get("/hevy/status")
async def hevy_status() -> dict:
    """Sync status: last sync time, template count, pushed routines."""
    conn = get_read_conn()
    try:
        sync_row = conn.execute(
            "SELECT last_sync_at, cursor FROM oauth_state WHERE source = 'hevy'"
        ).fetchone()
        template_count = conn.execute(
            "SELECT COUNT(*) FROM hevy_exercise_templates"
        ).fetchone()[0]
        routine_rows = conn.execute(
            "SELECT date, routine_id, title, pushed_at FROM hevy_routines ORDER BY date DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()

    return {
        "last_sync_at": sync_row[0] if sync_row else None,
        "has_cursor": bool(sync_row and sync_row[1]),
        "exercise_template_count": template_count,
        "recent_routines": [
            {"date": str(r[0]), "routine_id": r[1], "title": r[2], "pushed_at": str(r[3])}
            for r in routine_rows
        ],
    }


@router.post("/hevy/sync", dependencies=[Depends(require_admin_key)])
async def hevy_sync() -> dict:
    """Trigger an immediate Hevy workout sync."""
    try:
        result = await hevy_ingest.sync_workouts()
        return {"ok": True, **result}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("Hevy sync failed")
        raise HTTPException(status_code=502, detail=f"Hevy API error: {e}") from e


@router.post("/hevy/sync-templates", dependencies=[Depends(require_admin_key)])
async def hevy_sync_templates() -> dict:
    """Refresh the exercise template cache from Hevy."""
    try:
        count = await hevy_ingest.sync_exercise_templates()
        return {"ok": True, "templates_synced": count}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("Hevy template sync failed")
        raise HTTPException(status_code=502, detail=f"Hevy API error: {e}") from e


@router.post("/hevy/push-routine", dependencies=[Depends(require_admin_key)])
async def hevy_push_routine(regen: bool = Query(default=False)) -> dict:
    """Push today's AI workout plan to Hevy as a routine.

    Fetches the plan from the workout/next endpoint (using cache unless regen=true),
    maps exercises to Hevy template IDs, and creates/updates the routine in Hevy.
    """
    # Reuse the workout plan generation logic from dashboard
    from shc.api.routers.dashboard import workout_next

    try:
        plan = await workout_next(regen=regen)
    except Exception as e:
        log.exception("Failed to generate workout plan")
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {e}") from e

    if not plan.get("blocks"):
        raise HTTPException(status_code=422, detail="Generated plan has no blocks")

    try:
        result = await hevy_ingest.push_routine(plan)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.exception("Hevy push-routine failed")
        raise HTTPException(status_code=502, detail=f"Hevy API error: {e}") from e

    from shc.ingest.hevy import _extract_routine_id
    routine_id = _extract_routine_id(result)
    return {
        "ok": True,
        "routine_id": routine_id,
        "plan_readiness_tier": plan.get("readiness_tier"),
        "plan_focus": plan.get("recommendation", {}).get("focus"),
    }
