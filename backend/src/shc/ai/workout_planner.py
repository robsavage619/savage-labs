from __future__ import annotations

"""Workout plan context builder, validator, and persistence layer.

Generation happens externally — either through the Claude chat interface
(preferred) or as a fallback via Ollama.  This module never calls an LLM
directly; it only:

  1. Loads Obsidian vault research for use in system prompts / chat context.
  2. Builds the per-request dynamic training context from the live DB
     (delegates all numerics to `shc.metrics.compute_daily_state`).
  3. Validates plan dicts against the schema AND the deterministic
     auto-regulation gates from `DailyState.gates`.
  4. Saves / loads plans to / from the workout_plans table.
"""

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx
from shc.metrics import compute_daily_state, muscle_group

log = logging.getLogger(__name__)

# ── Vault research ────────────────────────────────────────────────────────────
# Delegated to shc.ai.vault — see that module for the full retrieval design.

from shc.ai.lab_findings import lab_findings_section
from shc.ai.vault import state_signals as _state_signals_fn
from shc.ai.vault import vault_context as _vault_context


def load_vault_research(
    state: dict[str, Any] | None = None,
    limit: int = 20,
    extra_signals: set[str] | None = None,
    keyword_hints: list[str] | None = None,
) -> str:
    return _vault_context(
        state=state, extra_signals=extra_signals, keyword_hints=keyword_hints, limit=limit
    )


def get_vault_research(state: dict[str, Any] | None = None) -> str:
    return _vault_context(state=state)


# ── Training context builder ──────────────────────────────────────────────────


def _workout_logged_today(conn) -> bool:
    """Return True if a strength workout has already been completed today."""
    row = conn.execute(
        "SELECT COUNT(*) FROM workouts WHERE started_at::DATE = current_date AND source = 'hevy'"
    ).fetchone()
    return bool(row and row[0] > 0)


def build_training_context(conn, planning_date: date | None = None) -> tuple[str, date]:
    """Build the per-request dynamic context string for plan generation.

    If `planning_date` is not supplied and a workout is already logged today,
    the context is computed for tomorrow so the plan covers the next session
    rather than forcing Active Recovery on the same day.

    Returns:
        (context_str, target_date) — callers use target_date when saving the plan.
    """
    # Local import to avoid the briefing → workout_planner → briefing cycle.
    from shc.ai.briefing import build_clinical_context

    real_today = date.today()
    if planning_date is None:
        planning_date = (
            (real_today + timedelta(days=1)) if _workout_logged_today(conn) else real_today
        )

    today = planning_date
    state = compute_daily_state(
        conn, planning_date=planning_date if planning_date != real_today else None
    )
    rec = state["recovery"]
    sleep = state["sleep"]
    load = state["training_load"]
    chk = state["checkin"]
    readiness = state["readiness"]
    gates = state["gates"]
    fresh = state["freshness"]

    # Content-only queries (exercise names, working weights, prefs, prior plan).
    workout_rows = conn.execute(
        """
        SELECT w.started_at::DATE AS day,
               STRING_AGG(DISTINCT ws.exercise, ', ') AS exercises,
               COUNT(*) AS sets,
               SUM(ws.weight_kg * ws.reps) AS volume_kg,
               AVG(ws.rpe) AS avg_rpe
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND w.started_at::DATE >= $since
        GROUP BY day ORDER BY day DESC
        """,
        {"since": (today - timedelta(days=30)).isoformat()},
    ).fetchall()
    ww_rows = conn.execute(
        "SELECT exercise, weight_kg, source FROM working_weights ORDER BY updated_at DESC"
    ).fetchall()
    # Best Epley e1RM per exercise (90d) — the basis for today's target load.
    # working_weights is an all-time ratcheting MAX, so prescribing off it at
    # higher reps demands a SUPRAMAXIMAL e1RM (a fake "deload"). Target load must
    # be derived from e1RM × today's intensity cap, not from the raw max weight.
    e1rm_by_ex = e1rm_by_exercise(conn, today)
    top_exercises = conn.execute(
        """
        SELECT ws.exercise, COUNT(*) AS sets, MAX(ws.weight_kg) AS max_kg,
               AVG(ws.rpe) AS avg_rpe
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE
          AND w.started_at::DATE >= $since
          AND ws.weight_kg IS NOT NULL
        GROUP BY ws.exercise ORDER BY sets DESC LIMIT 20
        """,
        {"since": (today - timedelta(days=90)).isoformat()},
    ).fetchall()
    prefs = conn.execute(
        "SELECT exercise, status, notes FROM exercise_preferences WHERE status IN ('no', 'sub')"
    ).fetchall()
    vol_rows = conn.execute(
        """
        SELECT date_trunc('week', w.started_at)::DATE AS week,
               COUNT(*) AS sets,
               SUM(ws.weight_kg * ws.reps) AS volume_kg
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND w.started_at::DATE >= $since
        GROUP BY week ORDER BY week
        """,
        {"since": (today - timedelta(days=56)).isoformat()},
    ).fetchall()

    # ── Closed loop: yesterday's plan + adherence ──────────────────────────
    prior_plan_row = conn.execute(
        "SELECT date, plan_json FROM workout_plans "
        "WHERE date < current_date ORDER BY date DESC LIMIT 1"
    ).fetchone()
    prior_plan: dict | None = None
    if prior_plan_row:
        try:
            prior_plan = json.loads(prior_plan_row[1])
            prior_plan["_date"] = str(prior_plan_row[0])
        except (json.JSONDecodeError, TypeError):
            prior_plan = None
    adherence_row = conn.execute(
        "SELECT plan_date, completion_pct, avg_rpe_actual, avg_rpe_target "
        "FROM plan_adherence ORDER BY date DESC LIMIT 1"
    ).fetchone()

    # Volume trend.
    vols = [float(r[2] or 0) for r in vol_rows]
    half = len(vols) // 2
    prior_vol = sum(vols[:half]) / max(half, 1) if half else 0
    recent_vol = sum(vols[half:]) / max(len(vols) - half, 1) if vols else 0
    vol_trend_pct = round((recent_vol - prior_vol) / prior_vol * 100, 1) if prior_vol > 0 else 0
    vol_trend_label = (
        f"+{vol_trend_pct}% (INCREASING — monitor ACWR)"
        if vol_trend_pct > 15
        else f"{vol_trend_pct}% (stable)"
        if -10 <= vol_trend_pct <= 15
        else f"{vol_trend_pct}% (decreasing)"
    )

    planning_label = f"PLANNING FOR: {today.isoformat()}"
    if today != real_today:
        planning_label += f"  (tomorrow — workout already completed today {real_today.isoformat()})"
    lines: list[str] = [f"{planning_label}\n"]

    clinical = build_clinical_context(conn)
    if clinical:
        lines.append(clinical + "\n")

    # ── Hard gates first — the LLM must respect these ──
    lines.append("## ⚠ AUTO-REGULATION GATES (HARD CONSTRAINTS)")
    lines.append(f"- Max intensity: **{gates['max_intensity'].upper()}**")
    if gates["forbid_muscle_groups"]:
        lines.append(f"- Forbidden muscle groups: {', '.join(gates['forbid_muscle_groups'])}")
    if gates["deload_required"]:
        lines.append(f"- DELOAD WEEK REQUIRED — {gates['deload_reason']}")
    if gates["hr_zone_shift_bpm"]:
        lines.append(
            f"- HR zones: shift −{gates['hr_zone_shift_bpm']} bpm "
            f"(propranolol day; HR-derived kcal ×{gates['kcal_multiplier']})"
        )
    for r in gates["reasons"]:
        lines.append(f"  · {r}")
    if not gates["reasons"]:
        lines.append("  · all clear — no overrides")

    # ── Load prescription rule — prevents the "deload = max attempt" bug ──
    cap_pct = load_cap_pct(gates)
    lines.append("\n## ⚠ LOAD PRESCRIPTION RULE (HARD CONSTRAINT)")
    lines.append(
        f"- Today's intensity ceiling is **{cap_pct}% of e1RM**. For every "
        "loaded exercise, the prescribed weight × reps must satisfy "
        f"`weight × (1 + reps/30) ≤ e1RM × {cap_pct / 100:.2f}`."
    )
    lines.append(
        "- NEVER prescribe a weight/rep combo whose Epley e1RM exceeds that "
        "ceiling. Holding the all-time working weight and just adding reps is a "
        "MAX ATTEMPT, not a deload — drop the weight instead."
    )
    lines.append(
        "- The WORKING WEIGHTS list below shows each lift's e1RM and today's "
        "load ceiling at 8 reps. Use the ceiling as your upper bound; pick reps "
        "to land at the prescribed RPE."
    )

    lines.append("\n## READINESS SNAPSHOT")
    if readiness["score"] is not None:
        adj = " (β-blocker reweighted)" if readiness["beta_blocker_adjusted"] else ""
        lines.append(
            f"- Composite readiness: {readiness['score']:.0f}/100 ({readiness['tier']}){adj}"
        )
    if rec["score"] is not None:
        tier = (
            "🟢 GREEN" if rec["score"] >= 67 else ("🟡 YELLOW" if rec["score"] >= 34 else "🔴 RED")
        )
        lines.append(f"- WHOOP recovery: {rec['score']:.0f} ({tier}) — {rec['score_date']}")
    if rec["hrv_sigma"] is not None:
        lines.append(
            f"- HRV: {rec['hrv_ms']:.1f}ms · 28d {rec['hrv_baseline_28d']:.1f}±{rec['hrv_sd_28d']:.1f}"
            f" · deviation {rec['hrv_sigma']:+.2f}σ"
        )
    if sleep["last_hours"] is not None:
        deep = f", deep {sleep['deep_pct_last'] * 100:.0f}%" if sleep["deep_pct_last"] else ""
        spo2 = f", SpO₂ {sleep['spo2_avg_last']:.1f}%" if sleep["spo2_avg_last"] else ""
        avg = f" · 7d avg {sleep['avg_7d']:.1f}h" if sleep["avg_7d"] else ""
        lines.append(f"- Sleep last night: {sleep['last_hours']:.1f}h{deep}{spo2}{avg}")
    if load["acwr"] is not None:
        zone = "safe" if 0.8 <= load["acwr"] <= 1.3 else ("⚠ HIGH" if load["acwr"] > 1.3 else "low")
        lines.append(
            f"- ACWR (true Gabbett, pooled): {load['acwr']} ({zone}) — "
            f"acute {load['acute_load_7d']:.1f} / chronic {load['chronic_load_28d']:.1f}"
        )

        def _zone(v: float | None) -> str:
            if v is None:
                return "n/a"
            return "safe" if 0.8 <= v <= 1.3 else ("⚠ HIGH" if v > 1.3 else "low")

        res, cond = load.get("resistance_acwr"), load.get("conditioning_acwr")
        lines.append(
            f"  · split → resistance (lifting): {res} ({_zone(res)}) — GATES INTENSITY · "
            f"conditioning (pickleball/cardio): {cond} ({_zone(cond)}) — gates court/legs"
        )
    if rec["rhr_7d_avg"] is not None:
        lines.append(
            f"- RHR: 7d avg {rec['rhr_7d_avg']:.0f} bpm "
            f"(28d {rec['rhr_baseline_28d']:.0f}, {rec['rhr_elevated_pct']:+.1f}%)"
        )
    if rec["skin_temp_delta"] is not None:
        lines.append(f"- Skin temp Δ {rec['skin_temp_delta']:+.2f}°C vs 28d baseline")

    # Daily check-in inputs.
    chk_parts: list[str] = []
    if chk["propranolol_taken"] is True:
        chk_parts.append("propranolol TAKEN")
    elif chk["propranolol_taken"] is False:
        chk_parts.append("no propranolol")
    if chk["soreness_overall"] is not None:
        chk_parts.append(f"soreness {chk['soreness_overall']}/10")
    if chk["sleep_quality"] is not None:
        chk_parts.append(f"sleep quality {chk['sleep_quality']}/10")
    if chk["body_weight_kg"] is not None:
        chk_parts.append(f"weight {chk['body_weight_kg']:.1f} kg")
    if chk["illness_flag"]:
        chk_parts.append("ILLNESS")
    if chk["travel_flag"]:
        chk_parts.append("travel")
    if chk_parts:
        lines.append(f"- Daily check-in: {' · '.join(chk_parts)}")
    sore_map = chk.get("muscle_soreness") or {}
    if sore_map:
        sev_label = {1: "mild", 2: "moderate", 3: "acute"}
        sore_groups: list[str] = []
        for muscle, sev in sorted(sore_map.items(), key=lambda kv: -kv[1]):
            label = sev_label.get(int(sev), f"{sev}")
            sore_groups.append(f"{muscle.replace('_', ' ')} {label}")
        lines.append(f"- Muscle soreness (body diagram): {', '.join(sore_groups)}")
    if chk["body_weight_trend_4wk"] is not None:
        lines.append(f"- Body weight trend (4wk): {chk['body_weight_trend_4wk']:+.2f}%")
    bc = state.get("body_composition", {})
    if bc.get("waist_to_shoulder") is not None:
        trend = (
            f"waist:shoulder 28d {bc['trend_28d_pct']:+.1f}% ({bc.get('trend_direction')})"
            if bc.get("trend_28d_pct") is not None
            else "no trend yet"
        )
        lines.append(
            f"- Body composition (photos): waist:shoulder {bc['waist_to_shoulder']:.3f}, "
            f"waist:hip {bc['waist_to_hip']:.3f}, {trend}"
        )
        if bc.get("note"):
            lines.append(f"  → {bc['note']} (recomp goal: lean out, keep size)")
    if fresh["gaps"]:
        for g in fresh["gaps"]:
            lines.append(f"- ⚠ {g}")

    # ── Closed loop: yesterday's plan vs reality ─────────────────────────
    if prior_plan or adherence_row:
        lines.append("\n## YESTERDAY'S PRESCRIPTION → EXECUTION")
        if prior_plan:
            rec_obj = prior_plan.get("recommendation", {})
            lines.append(
                f"- Prescribed ({prior_plan.get('_date', '?')}): "
                f"{rec_obj.get('intensity', '?')} intensity, "
                f"{rec_obj.get('focus', '?')}, target RPE {rec_obj.get('target_rpe', '?')}"
            )
        if adherence_row:
            comp = adherence_row[1]
            actual_rpe = adherence_row[2]
            target_rpe = adherence_row[3]
            lines.append(
                f"- Adherence: {comp:.0f}% sets completed"
                if comp is not None
                else "- Adherence: not yet logged"
            )
            if actual_rpe and target_rpe:
                delta = actual_rpe - target_rpe
                lines.append(
                    f"- RPE delivered: {actual_rpe:.1f} vs target {target_rpe:.1f} ({delta:+.1f})"
                )

    # Muscle-group rest status.
    lines.append("\n## MUSCLE GROUP REST STATUS")
    grp_rest = {
        "legs": load["days_since_legs"],
        "push": load["days_since_push"],
        "pull": load["days_since_pull"],
    }
    most = max(grp_rest.values())
    for g, d_val in sorted(grp_rest.items(), key=lambda x: -x[1]):
        flag = " ← MOST RESTED" if d_val == most else ""
        forbid = " ← FORBIDDEN BY GATE" if g in gates["forbid_muscle_groups"] else ""
        lines.append(f"- {g}: {d_val}d since last session{flag}{forbid}")

    history_limit = 14
    lines.append(f"\n## TRAINING HISTORY (last 30 days — {len(workout_rows)} sessions)")
    for row in workout_rows[:history_limit]:
        vol_str = f"{row[3] / 1000:.1f} tonnes" if row[3] else "bw/machine"
        rpe_str = f" @RPE {row[4]:.1f}" if row[4] else ""
        ex_preview = (row[1] or "")[:120]
        lines.append(f"- {row[0]}: {row[2]} sets | {vol_str}{rpe_str} | {ex_preview}")
    if len(workout_rows) > history_limit:
        lines.append(
            f"  ... {len(workout_rows) - history_limit} older sessions truncated "
            f"(showing {history_limit} most recent of {len(workout_rows)})"
        )

    ww_limit = 40
    lines.append(
        f"\n## WORKING WEIGHTS ({len(ww_rows)} exercises on record) — "
        f"all-time max · e1RM · today's ceiling ({cap_pct}% @8 reps)"
    )
    for ex, wkg, src in ww_rows[:ww_limit]:
        lbs = round(wkg * 2.20462, 1) if wkg else 0
        e1rm_kg = e1rm_by_ex.get(ex)
        if e1rm_kg:
            e1rm_lbs = round(e1rm_kg * 2.20462, 1)
            ceiling_lbs = round(e1rm_kg * (cap_pct / 100) / (1 + 8 / 30) * 2.20462, 1)
            extra = f" · e1RM ~{e1rm_lbs} · today ≤{ceiling_lbs} lbs @8"
        else:
            extra = " · e1RM n/a — set load by feel to RPE on first set"
        lines.append(f"- {ex}: {lbs} lbs ({wkg:.1f} kg) [{src}]{extra}")
    if len(ww_rows) > ww_limit:
        lines.append(
            f"  ... {len(ww_rows) - ww_limit} more truncated "
            f"(showing {ww_limit} most-recently-updated of {len(ww_rows)})"
        )

    lines.append(
        f"\n## TOP EXERCISES (last 90d by frequency — top {len(top_exercises)}, "
        f"capped at SQL LIMIT 20)"
    )
    for ex, sets, max_kg, avg_rpe in top_exercises:
        lbs = round(max_kg * 2.20462, 1) if max_kg else "bw"
        rpe_str = f" @RPE {avg_rpe:.1f}" if avg_rpe else ""
        lines.append(f"- {ex}: {sets} sets, max {lbs} lbs{rpe_str}")

    lines.append(f"\n## VOLUME TREND (8-week): {vol_trend_label}")
    if gates["e1rm_regression_4wk_pct"] is not None:
        lines.append(
            f"- e1RM regression on primary lift (4wk): {gates['e1rm_regression_4wk_pct']:+.1f}%"
        )

    # Push:pull balance commentary.
    if load["push_pull_ratio_28d"] is not None:
        ratio = load["push_pull_ratio_28d"]
        if ratio > 1.4:
            balance_note = f"⚠ PUSH-DOMINANT ({ratio:.2f}) — bias today toward pull"
        elif ratio < 0.7:
            balance_note = f"⚠ PULL-DOMINANT ({ratio:.2f}) — bias today toward push"
        else:
            balance_note = f"balanced ({ratio:.2f})"
        lines.append(
            f"\n## MUSCLE BALANCE (28d sets): "
            f"push {load['push_sets_28d']} | pull {load['pull_sets_28d']} | "
            f"legs {load['legs_sets_28d']}"
        )
        lines.append(f"- Status: {balance_note}")

    # Cardio mix.
    cardio_rows = conn.execute(
        """
        SELECT modality, SUM(duration_min) AS minutes, COUNT(*) AS sessions, AVG(avg_hr) AS avg_hr
        FROM cardio_sessions
        WHERE date >= (current_date - INTERVAL '28 days')
          AND modality NOT IN ('yoga', 'meditation', 'cross country skiing')
        GROUP BY modality ORDER BY minutes DESC
        """
    ).fetchall()
    if cardio_rows:
        lines.append(
            f"\n## CARDIO MIX (last 28 days — {load['cardio_min_28d']} min total, {load['cardio_z2_min_7d']} Z2 min in last 7d)"
        )
        for mod, mins, sess, avg_hr in cardio_rows:
            hr_str = f", avg HR {int(avg_hr)}" if avg_hr else ""
            lines.append(f"- {mod}: {int(mins or 0)} min over {sess} sessions{hr_str}")
    else:
        lines.append(
            "\n## CARDIO MIX (last 28 days): none logged — fat-loss programming should add Z2 + finisher"
        )

    lines.append("\n## MISSION + GOALS")
    lines.append("Rob is 40 and refuses to let age define his ceiling. This is not a maintenance")
    lines.append("program — it is a hypertrophy program engineered to build muscle. Age brings")
    lines.append("wisdom about recovery; it does not lower the ambition.")
    lines.append("")
    lines.append("PRIMARY GOAL: build muscle. Engineer the physique through per-muscle volume")
    lines.append("  progression — drive each muscle through MEV→MAV→MRV, add stimulus where it's")
    lines.append("  productive, back off where recovery says so. The PER-MUSCLE VOLUME table and")
    lines.append("  THIS WEEK'S PRESCRIPTION below are the program — build the session from them.")
    lines.append("  Emphasis: biceps and glutes are lagging and prioritized — bias direct volume")
    lines.append("  toward them whenever the gates and recovery allow.")
    lines.append("")
    lines.append("BODY-COMP: strict recomp at maintenance — build muscle and lean out at the same")
    lines.append("  time. Heavy compounds first for the strength base, then targeted hypertrophy")
    lines.append("  volume for the lagging and emphasis muscles.")
    lines.append("")
    lines.append("CARDIO is a supporting track — Z2 aerobic base + conditioning finishers for work")
    lines.append("  capacity, recovery, and the fat-loss side of recomp. It serves the build; it")
    lines.append("  never displaces a lift on a green day.")
    lines.append("")
    lines.append("PICKLEBALL is logged load only — Rob trains his own court skills. Treat his play")
    lines.append("  purely as a leg/conditioning stimulus that debits lower-body recovery; never")
    lines.append("  program drills, court work, or DUPR goals.")
    lines.append("")
    lines.append(
        "Design sessions that push. When gates say go, GO. A soft session on a green day is a"
    )
    lines.append(
        "missed adaptation and an insult to the goal. Respect the gates when they fire — they"
    )
    lines.append("fire to protect training quality, not to make the program easier.")

    if prefs:
        lines.append("\n## EXERCISES TO AVOID/SUBSTITUTE")
        for ex, status, notes in prefs:
            lines.append(f"- {ex} ({status})" + (f": {notes}" if notes else ""))

    # ── Your exercise notes (from Hevy) ───────────────────────────────────────
    try:
        note_rows = conn.execute(
            """
            SELECT ws.exercise, MAX(w.started_at)::DATE AS session_date, ws.exercise_notes
            FROM workout_sets ws
            JOIN workouts w ON w.id = ws.workout_id
            WHERE ws.exercise_notes IS NOT NULL
              AND ws.exercise_notes != ''
              AND w.started_at >= (current_date - INTERVAL '60 days')
            GROUP BY ws.exercise, ws.exercise_notes
            ORDER BY session_date DESC
            LIMIT 30
            """
        ).fetchall()
        if note_rows:
            lines.append("\n## YOUR EXERCISE NOTES (from Hevy — read these carefully)")
            lines.append("These are comments you wrote in Hevy after completing exercises.")
            lines.append("Use them to adjust load, cues, form, or exercise selection today.")
            for exercise, session_date, note in note_rows:
                lines.append(f'- {exercise} ({session_date}): "{note}"')
    except Exception as _e:
        log.debug("exercise notes unavailable: %s", _e)

    # ── Hevy exercise catalog ─────────────────────────────────────────────────
    try:
        hevy_tmpl_rows = conn.execute(
            "SELECT title, primary_muscle_group FROM hevy_exercise_templates ORDER BY primary_muscle_group, title"
        ).fetchall()
        if hevy_tmpl_rows:
            from collections import defaultdict

            by_group: dict[str, list[str]] = defaultdict(list)
            for title, pmg in hevy_tmpl_rows:
                by_group[pmg or "Other"].append(title)
            lines.append(
                f"\n## AVAILABLE HEVY EXERCISES ({len(hevy_tmpl_rows)} total — use VERBATIM names)"
            )
            for group in sorted(by_group):
                lines.append(f"### {group}")
                for ex in by_group[group]:
                    lines.append(f"- {ex}")
    except Exception as _e:
        log.debug("hevy_exercise_templates not available: %s", _e)

    # ── Mesocycle + progression context ──────────────────────────────────────
    try:
        from shc.training.mesocycle import mesocycle_context_block

        meso_block = mesocycle_context_block(conn)
        if meso_block:
            lines.append("\n" + meso_block)
    except Exception as _e:
        log.debug("mesocycle context unavailable: %s", _e)

    # ── Self-learning prescription — the per-muscle build order ───────────────
    try:
        from shc.training.autoregulation import prescription_context_block

        rx_block = prescription_context_block(conn)
        if rx_block:
            lines.append("\n" + rx_block)
    except Exception as _e:
        log.debug("prescription context unavailable: %s", _e)

    # ── Vault research — catalog + excerpts ───────────────────────────────────
    extra: set[str] = set()
    ratio = load.get("push_pull_ratio_28d")
    if ratio is not None and (ratio > 1.3 or ratio < 0.75):
        extra.add("push_pull_imbalance")
    if abs(vol_trend_pct) > 40:
        extra.add("volume_spike")

    # Keyword hints surface notes that match the session's movement/muscle focus.
    # Pull these from soreness, balance imbalance, and recent exercise names.
    hints: list[str] = ["hypertrophy", "strength", "progressive overload", "periodization"]
    if ratio is not None and ratio > 1.3:
        hints += ["pull", "posterior chain", "row", "lat"]
    elif ratio is not None and ratio < 0.75:
        hints += ["push", "chest", "press", "anterior"]
    try:
        sore_row = conn.execute(
            "SELECT muscle_soreness FROM daily_checkin WHERE date = current_date LIMIT 1"
        ).fetchone()
        if sore_row and sore_row[0]:
            import json as _json

            sore_map = _json.loads(sore_row[0]) if isinstance(sore_row[0], str) else sore_row[0]
            hints.extend(k for k, v in sore_map.items() if (v or 0) >= 2)
    except Exception:
        pass

    lab = lab_findings_section(conn)
    if lab:
        lines.append("\n" + lab)

    # Restate the hard gates immediately before the (large) vault block so the
    # binding constraints sit adjacent to where the plan is reasoned, not buried
    # above a wall of research (lost-in-the-middle mitigation).
    lines.append("\n## ⚠ CONSTRAINT RECAP (read before planning — these are HARD)")
    lines.append(
        f"- Max intensity: **{gates['max_intensity'].upper()}** · load ceiling **{cap_pct}% of e1RM**"
    )
    if gates["forbid_muscle_groups"]:
        lines.append(f"- Forbidden muscle groups: {', '.join(gates['forbid_muscle_groups'])}")
    if gates["deload_required"]:
        lines.append(
            f"- DELOAD REQUIRED — ≤moderate intensity, target RPE ≤7 ({gates['deload_reason']})"
        )
    lines.append(
        "- Cite vault notes by exact `filename.md`; every citation must be a real catalog note."
    )

    # Schema stub — placed immediately before vault research so the binding
    # contract sits within ~500 tokens of generation start (lost-in-the-middle
    # mitigation). TypeScript interface is 40% more token-efficient than JSON Schema.
    lines.append("""\
\n## OUTPUT SCHEMA (validator enforces this — deviations will be rejected)
```typescript
interface Plan {
  readiness_tier: "green" | "yellow" | "red";         // exact lowercase
  readiness_summary: string;
  recommendation: {
    intensity: "high" | "moderate" | "low" | "rest";  // exact lowercase
    focus: string;
    rationale: string;
    estimated_duration_min: number;
    target_rpe: number;
  };
  warmup: Array<{ name: string; sets: number; reps: number | string }>;
  blocks: Array<{
    label: string;          // NOT "name" — key must be "label"
    exercises: Array<{
      name: string;
      sets: number;
      reps: number | string;
      weight_lbs: number | null;
      rpe_target: number;
      rest_seconds: number; // REQUIRED on every exercise, no exceptions
      notes: string;
    }>;
  }>;
  cooldown: string;         // plain string, NOT array
  clinical_notes: string[];
  vault_insights: string[]; // cite real *.md filenames only
}
```
""")

    vault = load_vault_research(state, extra_signals=extra, keyword_hints=hints)
    if vault:
        lines.append("\n" + vault)

    return "\n".join(lines), today


# ── Validation + auto-regulation gate ────────────────────────────────────────


class GateViolation(ValueError):
    """Raised when a plan violates a hard auto-regulation gate."""


def load_cap_pct(gates: dict[str, Any]) -> int:
    """Today's load ceiling as a percentage of e1RM, from the gates.

    The ceiling stops recovery/deload days from prescribing supramaximal loads.
    A genuine HIGH day must sit ABOVE 100% — e1RM is an estimate, and beating it
    is exactly how progressive overload registers a new peak. Capping high days
    at <100% would freeze the strength ceiling and create a different "stuck"
    loop. The 3% tolerance in the validator stacks on top of these.
    """
    if gates.get("deload_required"):
        return 70
    return {"low": 78, "moderate": 90}.get(gates.get("max_intensity", "high"), 103)


def e1rm_by_exercise(conn, today: date, days: int = 90) -> dict[str, float]:
    """Best Epley e1RM (kg) per exercise over the window. Basis for target load.

    Reps are capped at 12 before estimating — Epley overestimates above ~10–12
    reps, so an uncapped MAX floats the ceiling up on fluky high-rep sets and
    partly defeats the deload guard it feeds (panel review M16).
    """
    rows = conn.execute(
        """
        SELECT ws.exercise, MAX(ws.weight_kg * (1 + LEAST(ws.reps, 12) / 30.0)) AS e1rm_kg
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL AND ws.reps > 0
          AND w.started_at::DATE >= $since
        GROUP BY ws.exercise
        """,
        {"since": (today - timedelta(days=days)).isoformat()},
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1]}


_CITATION_RE = re.compile(r"`?\b([\w-]+\.md)\b`?")


class CitationError(ValueError):
    """Raised when a plan cites vault research that doesn't exist."""


def _validate_citations(plan: dict[str, Any], allowed: set[str]) -> None:
    """Reject plans whose vault_insights cite notes outside the real vault.

    Every ``*.md`` filename referenced in a vault_insight must be a real note,
    and at least one insight must cite a real note — this is what stops the
    model (or a decorative fallback) from fabricating citations. Skipped when
    ``allowed`` is empty (vault unavailable), so missing-vault never blocks a plan.
    """
    if not allowed:
        return
    insights = plan.get("vault_insights") or []
    cited: set[str] = set()
    for insight in insights:
        text = insight if isinstance(insight, str) else str(insight.get("source", ""))
        cited.update(m.group(1) for m in _CITATION_RE.finditer(text))
    unknown = cited - allowed
    if unknown:
        raise CitationError(
            f"vault_insights cite notes not in the vault: {sorted(unknown)}. "
            "Cite only real filenames from the VAULT CATALOG."
        )
    if not cited:
        raise CitationError(
            "vault_insights cite no real vault note (`filename.md`). Every plan "
            "must ground at least one decision in a real catalog note."
        )


def _first_int(value: Any) -> int | None:
    """Parse the leading integer from a reps field ('10-12', '10 each side')."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = re.search(r"\d+", value)
        if m:
            return int(m.group())
    return None


def _exercise_targets_group(exercise: str, group: str) -> bool:
    return muscle_group(exercise) == group


def validate_plan(
    plan: dict[str, Any],
    state: dict[str, Any] | None = None,
    e1rm_ceilings: dict[str, float] | None = None,
    allowed_citations: set[str] | None = None,
) -> bool:
    """Validate a plan dict against the schema AND the deterministic gates.

    The schema check verifies shape (intensity enum, blocks present, etc.).
    The gate check verifies the plan respects today's hard auto-regulation
    constraints — max intensity, forbidden muscle groups, deload requirement.
    Pass `state` (a `DailyState` dict) to enable gate enforcement; omitting
    it falls back to schema-only validation for backwards compatibility.

    Pass `e1rm_ceilings` (exercise → e1RM kg) to enforce the per-exercise load
    ceiling — rejects any prescribed weight×reps whose Epley e1RM exceeds today's
    intensity cap. This is what stops a "deload" from being a max attempt.

    Pass `allowed_citations` (the set of real vault filenames) to enforce that
    every research citation in `vault_insights` maps to a real note. Omitting it
    skips the citation check (schema-only, for tests / backwards compatibility).

    Raises:
        ValueError: on schema violation.
        GateViolation: on auto-regulation gate violation.
        CitationError: on a vault citation that doesn't map to a real note.
    """
    if plan.get("readiness_tier") not in {"green", "yellow", "red"}:
        raise ValueError(f"Invalid readiness_tier: {plan.get('readiness_tier')!r}")
    rec = plan.get("recommendation", {})
    if rec.get("intensity") not in {"high", "moderate", "low", "rest"}:
        raise ValueError(f"Invalid intensity: {rec.get('intensity')!r} — must be string enum")
    if not rec.get("focus"):
        raise ValueError("recommendation.focus is empty")
    blocks = plan.get("blocks", [])
    if not blocks:
        raise ValueError("Plan has no blocks")
    for i, block in enumerate(blocks):
        if not block.get("label"):
            raise ValueError(f"Block {i} missing required 'label' field (got 'name'?)")
        if not block.get("exercises"):
            raise ValueError(f"Block {i} ({block.get('label')!r}) has no exercises")
        for j, ex in enumerate(block["exercises"]):
            if not ex.get("name"):
                raise ValueError(f"Block {i} exercise {j} missing 'name' (got 'exercise'?)")
            if ex.get("rest_seconds") is None:
                raise ValueError(
                    f"Block {i} exercise {j} ({ex.get('name')!r}) missing required 'rest_seconds'"
                )
    if not isinstance(plan.get("cooldown"), str):
        raise ValueError("cooldown must be a plain string, not an array or object")
    if not plan.get("clinical_notes"):
        raise ValueError("clinical_notes is empty — must include medication context")
    if not plan.get("vault_insights"):
        raise ValueError("vault_insights is empty — must cite research")
    if allowed_citations is not None:
        _validate_citations(plan, allowed_citations)

    # Auto-regulation gate enforcement.
    if state is not None:
        gates = state.get("gates", {})
        order = ("rest", "low", "moderate", "high")
        max_allowed = gates.get("max_intensity", "high")
        if rec["intensity"] not in order:
            raise ValueError(f"Invalid intensity: {rec['intensity']!r}")
        if order.index(rec["intensity"]) > order.index(max_allowed):
            raise GateViolation(
                f"Plan intensity {rec['intensity']!r} exceeds gate {max_allowed!r}. "
                f"Reasons: {'; '.join(gates.get('reasons', [])) or 'see DailyState.gates'}"
            )
        forbid = set(gates.get("forbid_muscle_groups", []))
        if forbid:
            for block in blocks:
                for ex in block.get("exercises", []):
                    g = muscle_group(ex.get("name", ""))
                    if g in forbid:
                        raise GateViolation(
                            f"Exercise {ex.get('name')!r} targets {g}, which is "
                            f"forbidden today (gate: {sorted(forbid)})."
                        )
        if gates.get("deload_required"):
            # Deload weeks must use moderate-or-lower intensity AND target_rpe <= 7.
            # If the recommendation omits target_rpe, derive it from the highest
            # per-exercise rpe_target in the plan so a low-RPE plan isn't rejected
            # because the field was absent (would have defaulted to 10).
            if (rpe_val := rec.get("target_rpe")) is not None:
                target_rpe = rpe_val
            else:
                target_rpe = max(
                    (
                        ex.get("rpe_target", 0)
                        for block in blocks
                        for ex in block.get("exercises", [])
                    ),
                    default=0,
                )
            if order.index(rec["intensity"]) > order.index("moderate") or target_rpe > 7:
                raise GateViolation(
                    f"Deload required ({gates.get('deload_reason')}) but plan is "
                    f"{rec['intensity']} @ RPE {target_rpe} — must be ≤moderate @ RPE ≤7."
                )

        # Per-exercise load ceiling: prescribed e1RM demand must not exceed
        # today's intensity cap. Stops the "hold the max weight, add reps"
        # pseudo-deload that demands a supramaximal effort.
        if e1rm_ceilings:
            cap = load_cap_pct(gates) / 100
            for block in blocks:
                for ex in block.get("exercises", []):
                    name = ex.get("name", "")
                    e1rm_kg = e1rm_ceilings.get(name)
                    w_lbs = ex.get("weight_lbs")
                    reps = _first_int(ex.get("reps"))
                    if not e1rm_kg or not w_lbs or not reps:
                        continue
                    demand_kg = (w_lbs / 2.20462) * (1 + reps / 30)
                    ceiling_kg = e1rm_kg * cap
                    # 3% tolerance for rounding/load-increment realities.
                    if demand_kg > ceiling_kg * 1.03:
                        demand_e1rm = round(demand_kg * 2.20462, 1)
                        ceil_e1rm = round(ceiling_kg * 2.20462, 1)
                        raise GateViolation(
                            f"{name!r} prescribed {w_lbs}lb×{reps} demands e1RM "
                            f"{demand_e1rm}lb, over today's {load_cap_pct(gates)}% "
                            f"ceiling of {ceil_e1rm}lb. Drop the weight — this is a "
                            "max attempt, not a deload."
                        )
    return True


# ── Persistence ────────────────────────────────────────────────────────────────


def _floor_loggable_rpe(plan: dict[str, Any]) -> None:
    """Raise sub-6 RPE targets to 6 on loaded lifts, in place.

    Hevy's RPE picker floors at 6, so a target below it (e.g. a deload set
    at RPE 5) can never be logged or autoregulated against. Cardio/bodyweight
    work (no ``weight_lbs``) is left alone — it isn't RPE-logged in Hevy.
    """
    floor = 6
    for block in plan.get("blocks", []):
        for ex in block.get("exercises", []):
            w = ex.get("weight_lbs")
            rpe = ex.get("rpe_target")
            if w is not None and w > 0 and rpe is not None and rpe < floor:
                ex["rpe_target"] = floor
    rec = plan.get("recommendation", {})
    if isinstance(rec.get("target_rpe"), (int, float)) and rec["target_rpe"] < floor:
        rec["target_rpe"] = floor


async def save_plan(
    plan: dict[str, Any], source: str = "claude", target_date: date | None = None
) -> None:
    """Persist a validated plan to workout_plans for the target date (defaults to today)."""
    _floor_loggable_rpe(plan)
    today = (target_date or date.today()).isoformat()
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO workout_plans (date, plan_json, source, created_at)
            VALUES ($date, $json, $src, now())
            ON CONFLICT (date) DO UPDATE SET
                plan_json = EXCLUDED.plan_json,
                source = EXCLUDED.source,
                created_at = EXCLUDED.created_at
            """,
            {"date": today, "json": json.dumps(plan), "src": source},
        )
    log.info("Saved workout plan for %s (source=%s)", today, source)


def load_plan(target_date: str | None = None) -> dict[str, Any] | None:
    """Load the stored plan for a given date (defaults to today).

    Returns:
        Plan dict or None if no plan exists for that date.
    """
    d = target_date or date.today().isoformat()
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT plan_json FROM workout_plans WHERE date = $d", {"d": d}
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else None


def build_midday_context(conn) -> str:
    """Build the prompt for Claude to generate a midday session recommendation.

    Reads today's DailyState and morning workout (if any) to determine whether
    lunch should be a workout (accessory lift, Z2 cardio, conditioning) or
    recovery (leg bags, sauna, hot tub). Returns a self-contained prompt string.
    """
    from shc.ai.briefing import build_clinical_context

    today = date.today()
    state = compute_daily_state(conn)
    rec = state["recovery"]
    load = state["training_load"]
    chk = state["checkin"]
    gates = state["gates"]

    # Did Rob already lift this morning?
    morning_row = conn.execute(
        """
        SELECT w.started_at, STRING_AGG(DISTINCT ws.exercise, ', ') AS exercises,
               COUNT(*) AS sets, AVG(ws.rpe) AS avg_rpe
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE w.started_at::DATE = current_date
          AND w.source = 'hevy'
          AND ws.is_warmup = FALSE
        GROUP BY w.started_at
        ORDER BY w.started_at DESC
        LIMIT 1
        """
    ).fetchone()

    # Cardio logged today (Apple Health)?
    cardio_row = conn.execute(
        "SELECT modality, duration_min, avg_hr FROM cardio_sessions WHERE date = current_date LIMIT 1"
    ).fetchone()

    lines: list[str] = [
        f"MIDDAY SESSION RECOMMENDATION — {today.isoformat()} (day of week: {today.strftime('%A')})\n"
    ]

    clinical = build_clinical_context(conn)
    if clinical:
        lines.append(clinical + "\n")

    lines.append("## AVAILABLE NIKE LUNCH-HOUR FACILITIES (60 min window)")
    lines.append("- Sauna")
    lines.append("- Hot tub")
    lines.append("- Leg bags / compression boots")
    lines.append("(No cold plunge or gym/court access at this location)\n")

    lines.append("## MIDDAY SESSION OPTIONS (all valid — choose the best fit)")
    lines.append(
        "- Accessory lift: 8–10 working sets targeting a DIFFERENT muscle group from this morning"
    )
    lines.append(
        "  (e.g. AM push → noon pull accessories; AM legs → noon upper body; AM pull → noon arms/shoulders)"
    )
    lines.append(
        "  Only valid when: ACWR ≤ 1.3, recovery GREEN, no deload, ≥4h since morning session."
    )
    lines.append(
        "  Rob logs this in Hevy himself — prescribe exact exercises, sets, reps, RPE targets."
    )
    lines.append("- Recovery: sauna, hot tub, leg bags (compression) — any combination")
    lines.append("- Zone 2 cardio (bike, treadmill, elliptical) — low HR, fat-burning base")
    lines.append("- Conditioning / HIIT — metabolic, body-comp push")
    lines.append("- Mobility / yoga / active stretching\n")

    lines.append("## THIS MORNING'S SESSION")
    if morning_row:
        started = morning_row[0]
        exercises_str = morning_row[1] or ""
        exercises_preview = exercises_str[:120]
        avg_rpe = morning_row[3]
        rpe_str = f" @avg RPE {avg_rpe:.1f}" if avg_rpe else ""
        # Derive muscle groups from exercise names using the Python helper.
        ex_names = [e.strip() for e in exercises_str.split(",") if e.strip()]
        groups = sorted({muscle_group(e) for e in ex_names} - {None})  # type: ignore[misc]
        groups_str = ", ".join(groups) if groups else "mixed"
        lines.append(f"- Lifted this morning ({started}): {morning_row[2]} sets{rpe_str}")
        lines.append(f"- Muscle groups trained: {groups_str}")
        lines.append(f"- Exercises: {exercises_preview}")
        lines.append(
            "→ This is a 2-a-day. A second lift is on the table if recovery is GREEN and ACWR ≤ 1.3 "
            "— target a DIFFERENT muscle group. Otherwise use recovery modalities."
        )
    elif cardio_row:
        lines.append(
            f"- Cardio this morning: {cardio_row[0]}, {cardio_row[1]} min, avg HR {cardio_row[2]}"
        )
    else:
        lines.append("- No workout logged yet today — midday could be the primary session.")

    lines.append("\n## RECOVERY STATE")
    if rec["score"] is not None:
        tier = "GREEN" if rec["score"] >= 67 else ("YELLOW" if rec["score"] >= 34 else "RED")
        lines.append(f"- WHOOP recovery: {rec['score']:.0f} ({tier})")
    if rec["hrv_sigma"] is not None:
        lines.append(f"- HRV: {rec['hrv_ms']:.1f}ms ({rec['hrv_sigma']:+.2f}σ vs 28d baseline)")
    if load["acwr"] is not None:
        zone = "SAFE" if 0.8 <= load["acwr"] <= 1.3 else ("⚠ HIGH" if load["acwr"] > 1.3 else "LOW")
        lines.append(f"- ACWR: {load['acwr']} ({zone})")
        if load["acwr"] > 1.5:
            lines.append("  → ACWR > 1.5: NO additional workout load. Recovery only.")
        elif load["acwr"] > 1.3:
            lines.append("  → ACWR > 1.3: Keep midday session light — active recovery or Z2 only.")

    chk_parts: list[str] = []
    if chk.get("soreness_overall") is not None:
        chk_parts.append(f"soreness {chk['soreness_overall']}/10")
    if chk.get("energy_level") is not None:
        chk_parts.append(f"energy {chk['energy_level']}/10")
    if chk_parts:
        lines.append(f"- Check-in: {' · '.join(chk_parts)}")

    sore_map = chk.get("muscle_soreness") or {}
    if sore_map:
        sore_parts = [f"{k.replace('_', ' ')}" for k, v in sore_map.items() if (v or 0) >= 2]
        if sore_parts:
            lines.append(f"- Significant soreness: {', '.join(sore_parts)}")

    lines.append("\n## AUTO-REGULATION GATES")
    lines.append(f"- Max intensity gate: {gates['max_intensity'].upper()}")
    if gates.get("deload_required"):
        lines.append(f"- DELOAD WEEK: {gates.get('deload_reason')} — keep midday light/recovery")
    for r in gates.get("reasons") or []:
        lines.append(f"  · {r}")

    lines.append("\n## TRAINING MANDATE")
    lines.append(
        "Rob is training to build muscle. This is not a wellness routine — it is a hypertrophy"
    )
    lines.append("program. The midday session is a CORE training block, not a bonus.")
    lines.append("")
    lines.append("Primary goal: build muscle — drive per-muscle volume through MEV→MAV→MRV, with")
    lines.append("biceps and glutes prioritized as lagging-emphasis muscles. Body-comp: strict")
    lines.append("recomp at maintenance (build muscle, lean out concurrently).")
    lines.append("")
    lines.append(
        "DEFAULT TO WORK. Recovery is prescribed when the body signals it (ACWR, HRV, gates)."
    )
    lines.append(
        "When those signals are clear, it is prescribed aggressively — thermal + compression is"
    )
    lines.append("not passive rest, it is active recovery that accelerates adaptation.")
    lines.append(
        "When signals are green, a real training stimulus is REQUIRED. A walk and a stretch"
    )
    lines.append("on a green-light day is a missed adaptation window and a failure of this system.")
    lines.append("")
    lines.append("Specific midday contributions to the build:")
    lines.append(
        "- 2-a-day accessory lift: the highest-value midday option — add direct volume to a"
    )
    lines.append("  lagging/emphasis muscle (biceps, glutes) or any muscle below MAV for the week.")
    lines.append(
        "- Z2 cardio (130–145 bpm): aerobic base + the fat-loss side of recomp, low recovery cost"
    )
    lines.append(
        "- Conditioning/HIIT: work capacity and conditioning — keep it from cutting into lifting recovery"
    )
    lines.append("- Recovery (when gated): maximizes adaptation from the morning session and")
    lines.append("  ensures the next session quality is high — not a rest day, a prep day")
    lines.append(
        "Pickleball is logged load only — Rob handles court skills himself; never program drills.\n"
    )

    lines.append("## OUTPUT — POST THIS JSON TO http://127.0.0.1:8000/api/midday/session")
    lines.append("""```json
{
  "session_type": "workout | recovery | mixed",
  "title": "<8–12 word title>",
  "duration_min": 60,
  "intensity": "high | moderate | low | passive",
  "activities": [
    {"name": "<activity>", "duration_min": <n>, "notes": "<execution cues, targets, why>"}
  ],
  "rationale": "<2-3 sentences: why this today, referencing morning session + recovery state>",
  "performance_goal": "<1 sentence: how this advances the muscle-building goal>"
}
```""")
    lines.append("")
    lines.append("Rules:")
    lines.append("- Total activity duration_min must sum to ≤ 60 (leave 5 min for transition).")
    lines.append(
        "- Accessory lift (2-a-day strength): ONLY valid when ACWR ≤ 1.3 AND recovery GREEN AND no deload."
    )
    lines.append("  Must target a different muscle group than this morning. Cap at 8–10 work sets.")
    lines.append(
        "  For lift activities, use notes to prescribe: exercise, sets × reps, weight/RPE target."
    )
    lines.append("  Rob logs these in Hevy — use exact Hevy exercise names where possible.")
    lines.append("- If ACWR > 1.5: session_type must be 'recovery', intensity must be 'passive'.")
    lines.append(
        "- If ACWR > 1.3: session_type must be 'recovery' or 'mixed', intensity ≤ 'low'. No lifting."
    )
    lines.append(
        "- Never prescribe recovery when a lift or workout is the right call — push the build."
    )
    lines.append("- POST the JSON to the endpoint above. No other output needed.")

    return "\n".join(lines)


def load_latest_plan() -> tuple[dict[str, Any], str] | None:
    """Load the most recent stored plan regardless of date.

    Returns:
        (plan_dict, plan_date_iso) or None if the table is empty.
    """
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT plan_json, date FROM workout_plans ORDER BY date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return json.loads(row[0]), str(row[1])
