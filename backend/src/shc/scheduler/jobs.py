from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shc.ingest import dupr, hevy, whoop

log = logging.getLogger(__name__)


async def _dupr_sync_safe() -> None:
    """Daily DUPR pull that no-ops quietly until credentials are configured."""
    try:
        await dupr.sync_rating()
    except RuntimeError as exc:
        log.info("skipping DUPR sync: %s", exc)
    except Exception:
        log.exception("DUPR sync failed")


async def _recompute_scores() -> None:
    """Nightly job: refresh per-exercise e1RM + Israetel performance scores.

    The autoregulation controller's volume decisions read these scores, so they
    must be current before the next plan is generated.
    """
    from shc.db.schema import write_ctx
    from shc.training.mesocycle import compute_all_scores

    async with write_ctx() as conn:
        compute_all_scores(conn)


async def _recompute_adherence() -> None:
    """Nightly job: link yesterday's plan to the workout that actually executed it."""
    import json
    from datetime import date, timedelta

    from shc.db.schema import write_ctx

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    async with write_ctx() as conn:
        prior = conn.execute(
            "SELECT date, plan_json FROM workout_plans WHERE date = $d",
            {"d": yesterday},
        ).fetchone()
        if not prior:
            return
        try:
            plan = json.loads(prior[1])
        except (json.JSONDecodeError, TypeError):
            return
        prescribed_sets = sum(
            int(ex.get("sets", 0) or 0)
            for block in plan.get("blocks", [])
            for ex in block.get("exercises", [])
        )
        rec = plan.get("recommendation", {})
        target_rpe = float(rec.get("target_rpe", 0) or 0) or None
        actual = conn.execute(
            """
            SELECT
                w.id,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup) AS sets_done,
                AVG(ws.rpe) FILTER (WHERE ws.rpe IS NOT NULL) AS avg_rpe
            FROM workouts w
            LEFT JOIN workout_sets ws ON ws.workout_id = w.id
            WHERE w.started_at::DATE = $d
            GROUP BY w.id
            ORDER BY w.started_at DESC LIMIT 1
            """,
            {"d": yesterday},
        ).fetchone()
        wid = actual[0] if actual else None
        sets_done = int(actual[1]) if actual and actual[1] else 0
        actual_rpe = float(actual[2]) if actual and actual[2] else None
        completion_pct = (
            round(sets_done / prescribed_sets * 100, 1) if prescribed_sets > 0 else None
        )
        conn.execute(
            """
            INSERT INTO plan_adherence
                (date, plan_date, workout_id, completion_pct,
                 avg_rpe_actual, avg_rpe_target, notes)
            VALUES ($d, $pd, $wid, $cp, $rpe, $tgt, NULL)
            ON CONFLICT (date) DO UPDATE SET
                plan_date = EXCLUDED.plan_date,
                workout_id = EXCLUDED.workout_id,
                completion_pct = EXCLUDED.completion_pct,
                avg_rpe_actual = EXCLUDED.avg_rpe_actual,
                avg_rpe_target = EXCLUDED.avg_rpe_target
            """,
            {
                "d": yesterday,
                "pd": yesterday,
                "wid": wid,
                "cp": completion_pct,
                "rpe": actual_rpe,
                "tgt": target_rpe,
            },
        )
    log.info("plan adherence recomputed for %s (sets %s/%s)", yesterday, sets_done, prescribed_sets)


_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        whoop.sync_all,
        "interval",
        hours=12,
        id="whoop_sync",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        hevy.sync_workouts,
        "interval",
        minutes=60,
        id="hevy_sync",
        replace_existing=True,
        misfire_grace_time=300,
    )
    # Closes the prescription→execution loop — runs after Hevy has synced,
    # writes plan_adherence row that build_training_context reads tomorrow.
    scheduler.add_job(
        _recompute_adherence,
        "cron",
        hour=4,
        minute=15,
        id="adherence_recompute",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Performance scores feed the autoregulation controller — recompute nightly,
    # after Hevy has synced and before the morning plan is generated.
    scheduler.add_job(
        _recompute_scores,
        "cron",
        hour=4,
        minute=0,
        id="scores_recompute",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # DUPR rating snapshot — once daily; ratings only move after matches post.
    scheduler.add_job(
        _dupr_sync_safe,
        "cron",
        hour=5,
        minute=30,
        id="dupr_sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info("registered APScheduler jobs")
