from __future__ import annotations

import asyncio
import logging
from datetime import datetime

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


async def _score_experiments() -> None:
    """Nightly job: refresh and rescore every active n-of-1 study.

    Scoring had no scheduled caller, so results sat unscored from 2026-09-04
    until a manual rescore on 2026-11-09 while their arms kept filling.
    """
    from shc import lab_queue, selflab
    from shc.db.schema import write_ctx

    async with write_ctx() as conn:
        promoted = lab_queue.promote_queue(conn)
        results = selflab.refresh_and_score_all(conn)
        idle = lab_queue.idle_notes(conn)
    for p in promoted:
        log.info("lab queue: %s", p)
    for note in idle:
        log.info("lab queue: %s", note)
    verdicts = [f"{r['experiment_id']}={r['verdict']}" for r in results if "verdict" in r]
    log.info("nightly experiment rescore: %s", ", ".join(verdicts) or "no active studies")


async def _run_research() -> None:
    """Nightly job: re-run every hypothesis, log the morning forecast, re-score the lab."""
    from shc import research, rob_model
    from shc.db.schema import write_ctx

    async with write_ctx() as conn:
        results = research.run_all(conn)
        # Log this morning's forecast before the reading lands, then re-score the lab.
        for target in research.FORECAST_TARGETS:
            research.forecast_today(conn, metric=target)
            research.store_backtest(conn, research.backtest(conn, metric=target))
        # After the run, so the model reads tonight's beliefs.
        model = rob_model.refresh(conn)
    log.info("nightly rob model refresh: %s", model)
    log.info(
        "nightly research run: %s",
        ", ".join(f"{r['slug']}={r['verdict']}" for r in results) or "no hypotheses",
    )


async def _reconcile_check() -> None:
    """Nightly job: run the reconciliation checks and alert the phone if any fails.

    The checks recompute engine numbers from raw rows, but they only ran when
    someone opened /api/training/reconcile, so a drift could sit unseen. The
    alert names the failing checks and nothing else.
    """
    from shc.db.schema import get_read_conn
    from shc.notify import send_phone_alert
    from shc.training.reconcile import run_all

    def _run() -> list:
        conn = get_read_conn()
        try:
            return run_all(conn)
        finally:
            conn.close()

    findings = await asyncio.to_thread(_run)
    failed = [f.check for f in findings if not f.ok]
    if not failed:
        log.info("nightly reconcile: %d of %d checks clean", len(findings), len(findings))
        return
    log.warning("nightly reconcile: %d of %d checks failed: %s", len(failed), len(findings), failed)
    await send_phone_alert(
        title="SHC reconcile failed",
        message=f"{len(failed)} of {len(findings)} checks failed: {', '.join(failed)}. "
        "Details: /api/training/reconcile",
    )


async def _retest_reminder() -> None:
    """Weekly job: one phone alert naming the markers due a re-test.

    Due means stale, drifting or out of range. The alert carries marker names
    only, never a value or a target.
    """
    from shc.db.schema import get_read_conn
    from shc.health_markers import names_due
    from shc.notify import send_phone_alert

    def _run() -> list[str]:
        conn = get_read_conn()
        try:
            return names_due(conn)
        finally:
            conn.close()

    due = await asyncio.to_thread(_run)
    if not due:
        log.info("weekly retest reminder: nothing due")
        return
    log.info("weekly retest reminder: %d markers due", len(due))
    await send_phone_alert(
        title="SHC re-test reminder",
        message=f"{len(due)} to re-check: {', '.join(due)}. Details: /api/healthspan",
    )


async def _adherence_prompts(kind: str) -> None:
    """Evening: send tomorrow's assignment. Morning: ask yesterday's one-tap question."""
    from datetime import date

    from shc import adherence_prompts
    from shc.db.schema import write_ctx
    from shc.notify import send_phone_alert

    build = (
        adherence_prompts.evening_prompts
        if kind == "evening"
        else adherence_prompts.morning_prompts
    )
    async with write_ctx() as conn:
        prompts = await asyncio.to_thread(build, conn, date.today())
    for p in prompts:
        if not await send_phone_alert(p.title, p.message, p.actions or None):
            log.warning("adherence %s prompt not delivered: %s", kind, p.title)


async def _backup_db() -> None:
    """Nightly job: keep a week of verified database copies."""
    from shc.config import settings
    from shc.db.schema import backup_database, write_ctx

    async with write_ctx() as conn:
        dest = await asyncio.to_thread(backup_database, conn, settings.backup_dir)
    log.info("database backed up to %s", dest)


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
        actual_rpe = float(actual[2]) if actual and actual[2] else None
        # Sets of the prescribed exercises only, each capped at its prescription, so a
        # fully swapped session can't read as 100% and an extra one can't exceed it.
        done_by_name = dict(
            conn.execute(
                """
                SELECT lower(ws.exercise), COUNT(*) FROM workout_sets ws
                WHERE ws.workout_id = $wid AND NOT ws.is_warmup GROUP BY 1
                """,
                {"wid": wid},
            ).fetchall()
        )
        matched_sets = 0
        for block in plan.get("blocks", []):
            for ex in block.get("exercises", []):
                name = str(ex.get("name", "")).lower()
                take = min(int(ex.get("sets", 0) or 0), done_by_name.get(name, 0))
                matched_sets += take
                done_by_name[name] = done_by_name.get(name, 0) - take
        completion_pct = (
            round(matched_sets / prescribed_sets * 100, 1) if prescribed_sets > 0 else None
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
    log.info(
        "plan adherence recomputed for %s (sets %s/%s)", yesterday, matched_sets, prescribed_sets
    )


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
            # DUPR syncing is disabled (see _dupr_sync_safe / sync_all) while
            # logins are paused pending re-verification at dupr.gg — alerting
            # on a source we've deliberately stopped syncing is just noise.
            "  AND source != 'dupr' "
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
    scheduler.add_job(
        _backup_db,
        "cron",
        hour=3,
        minute=30,
        id="db_backup",
        replace_existing=True,
        misfire_grace_time=6 * 3600,
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
    # Rescore the n-of-1 portfolio after the 4:00–4:30 jobs, before the morning
    # plan. A newly CONFIRMED randomized study emits its prior here.
    scheduler.add_job(
        _score_experiments,
        "cron",
        hour=4,
        minute=45,
        id="experiments_score",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        _run_research,
        "cron",
        hour=4,
        minute=50,
        id="research_run",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # After the research run, before the morning: recompute the engine's numbers
    # from raw rows and push a phone alert if any check fails.
    scheduler.add_job(
        _reconcile_check,
        "cron",
        hour=5,
        minute=0,
        id="reconcile_check",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Weekly, after the reconcile check: names of markers due a re-test.
    scheduler.add_job(
        _retest_reminder,
        "cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        id="retest_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # DUPR rating snapshot. The session renews itself from a linked refresh token;
    # a password login (which emails a code) only runs when that chain is broken, and
    # it pauses itself after one refusal so this job cannot spam.
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
    # Phone drops the daily Apple Health payload in iCloud; runs at startup so
    # files that arrived while the lid was shut are picked up on wake.
    scheduler.add_job(
        _ingest_shortcut_inbox,
        "interval",
        minutes=15,
        id="shortcut_inbox",
        replace_existing=True,
        misfire_grace_time=900,
        next_run_time=datetime.now(),
    )
    for kind, hour in (("evening", 20), ("morning", 8)):
        scheduler.add_job(
            _adherence_prompts,
            "cron",
            args=[kind],
            hour=hour,
            minute=0,
            id=f"adherence_prompt_{kind}",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    log.info("registered APScheduler jobs")


async def _ingest_shortcut_inbox() -> None:
    from shc.api.routers.apple import ingest_shortcut_inbox
    from shc.config import settings

    await ingest_shortcut_inbox(settings.shortcut_inbox_dir)
