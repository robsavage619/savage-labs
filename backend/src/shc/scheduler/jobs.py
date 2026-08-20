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

    After recompute, the nightly path mirrors the manual recompute (#7): if the
    engine's prescription accuracy is degrading, re-fit the self-learning bands
    and landmarks so the next plan is built on refreshed parameters. The API
    endpoint covers manual recompute; this covers the unattended path.
    """
    from shc.db.schema import write_ctx
    from shc.training.mesocycle import compute_all_scores, ensure_active_mesocycle
    from shc.training.self_learning import (
        acwr_fit_data_changed_since_last_fit,
        detect_accuracy_degradation,
        fit_all,
    )

    async with write_ctx() as conn:
        compute_all_scores(conn)
        deg = detect_accuracy_degradation(conn)
        if deg.get("degrading"):
            if acwr_fit_data_changed_since_last_fit(conn):
                fit_all(conn, ensure_active_mesocycle(conn).id)
                log.warning(
                    "engine accuracy degradation — re-fit triggered: %s", deg.get("message")
                )
            else:
                log.info(
                    "engine accuracy degradation detected but no new data since last "
                    "ACWR fit — skipping re-fit (would be a no-op): %s",
                    deg.get("message"),
                )


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
        # Order by sets_done, NOT started_at: WHOOP mirrors every Hevy lift as its own
        # workout row a second or two later, with zero sets. Picking the latest workout
        # therefore selected the WHOOP shadow and scored every session 0% complete.
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
            ORDER BY sets_done DESC, MAX(w.started_at) DESC LIMIT 1
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


async def _auto_advance_mesocycle() -> None:
    """Roll a finished block forward so it can't latch in permanent calendar deload.

    A block's deload flag is pure calendar math (``week_number > planned_weeks``);
    nothing previously advanced the block, so once it passed its planned weeks it
    flagged deload indefinitely and every prescription thereafter halved volume.
    This drives the two-phase state machine on a calendar dwell:

      * accumulation done (week_number > planned_weeks) → enter the deload week
      * deload week elapsed (week_number > planned_weeks + 1) → start a fresh block

    week_number counts from the original ``started_on`` and is unaffected by the
    active→deloading transition, so it is a stable dwell gate for both steps.
    """
    from shc.db.schema import write_ctx
    from shc.training.mesocycle import advance_mesocycle, ensure_active_mesocycle

    async with write_ctx() as conn:
        state = ensure_active_mesocycle(conn)
        if state.status == "active" and state.week_number > state.planned_weeks:
            advance_mesocycle(conn, trigger="auto-calendar")
            log.warning(
                "mesocycle %s past planned %dwk (week %d) — entering deload",
                state.id,
                state.planned_weeks,
                state.week_number,
            )
        elif state.status == "deloading" and state.week_number > state.planned_weeks + 1:
            new = advance_mesocycle(conn, trigger="auto-calendar")
            log.warning(
                "mesocycle %s deload week elapsed — starting fresh accumulation block %s",
                state.id,
                new.id,
            )


_scheduler: AsyncIOScheduler | None = None


# How long a source stays broken before Rob is reminded a second time. A single
# banner is easy to miss while it is on screen and impossible to recover once it
# is gone, and the failure this exists for went unnoticed for 2.5 days.
REAUTH_RENAG_HOURS = 6

# Where each source is reconnected. WHOOP's OAuth entry point is mounted under
# /auth, NOT /api — the /api path 404s.
_REAUTH_URLS = {
    "whoop": "http://127.0.0.1:8000/auth/whoop/login",
}


async def _check_reauth_alerts() -> None:
    """Push a desktop alert when a data source needs reauthorization.

    `oauth_state.needs_reauth` was pull-only for its whole life: correct, and
    invisible until someone opened the app. This closes the loop. It alerts on
    the transition into a broken state, re-nags every REAUTH_RENAG_HOURS while
    it stays broken, and re-arms once the source reconnects.
    """
    from datetime import UTC, datetime, timedelta

    from shc.db.schema import write_ctx
    from shc.notify import send_desktop_alert

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=REAUTH_RENAG_HOURS)

    async with write_ctx() as conn:
        # Re-arm reconnected sources first, so a source that broke, was fixed,
        # and broke again inside one window still alerts the second time.
        conn.execute(
            "UPDATE oauth_state SET reauth_alerted_at = NULL "
            "WHERE needs_reauth = FALSE AND reauth_alerted_at IS NOT NULL"
        )
        due = conn.execute(
            "SELECT source, last_sync_at, reauth_alerted_at FROM oauth_state "
            "WHERE needs_reauth = TRUE "
            "  AND (reauth_alerted_at IS NULL OR reauth_alerted_at < ?)",
            [cutoff],
        ).fetchall()

    for source, last_sync_at, alerted_at in due:
        stale_for = ""
        if last_sync_at is not None:
            last = last_sync_at if last_sync_at.tzinfo else last_sync_at.replace(tzinfo=UTC)
            hours = (now - last).total_seconds() / 3600
            stale_for = (
                f" Data is {hours / 24:.1f} days stale."
                if hours >= 24
                else f" Data is {hours:.0f}h stale."
            )

        url = _REAUTH_URLS.get(source)
        message = f"Reconnect: {url}" if url else "Reconnect this source in the app."
        delivered = await send_desktop_alert(
            title=f"{source.upper()} needs reauthorization",
            subtitle=f"Syncs have been failing.{stale_for}",
            message=message,
        )
        # Stamp ONLY on delivery, so an undelivered alert is retried on the next
        # poll instead of being silently consumed. The first cut stamped
        # unconditionally to avoid a log flood, which had the failure backwards:
        # the common reason a banner does not land is that there is no GUI
        # session to receive it right now, and that is precisely the case where
        # it must be retried rather than dropped. A genuinely broken notifier
        # logging every 30 min is noise attached to a real broken source, which
        # is the condition we want loud anyway.
        if delivered:
            async with write_ctx() as conn:
                conn.execute(
                    "UPDATE oauth_state SET reauth_alerted_at = ? WHERE source = ?", [now, source]
                )
        log.warning(
            "%s needs reauth (%s alert, delivered=%s) — %s",
            source,
            "first" if alerted_at is None else "repeat",
            delivered,
            url or "no reauth URL configured",
        )


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
    # Roll the mesocycle forward when a block is past its planned weeks, so it
    # can't latch in permanent calendar deload. Runs after scores/adherence and
    # before the morning plan is generated.
    scheduler.add_job(
        _auto_advance_mesocycle,
        "cron",
        hour=4,
        minute=30,
        id="mesocycle_auto_advance",
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
    # A dead OAuth token is silent by construction: the API keeps serving the
    # last-known numbers. Poll often enough that a break costs minutes, not days.
    scheduler.add_job(
        _check_reauth_alerts,
        "interval",
        minutes=30,
        id="reauth_alert_check",
        replace_existing=True,
        misfire_grace_time=900,
    )
    log.info("registered APScheduler jobs")
