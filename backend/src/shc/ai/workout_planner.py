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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx
from shc.metrics import compute_daily_state, muscle_group

log = logging.getLogger(__name__)

# ── Vault research ────────────────────────────────────────────────────────────

_VAULT_NOTES = [
    "kiviniemi-2007-hrv-guided-endurance-training.md",
    "plews-2013-hrv-monitoring-compliance.md",
    "overreaching-detection.md",
    "fitness-fatigue-theory.md",
    "progressive-overload-strength.md",
    "training-frequency-strength.md",
]

_KEEP_HEADINGS = {
    "## Summary",
    "## Prescription",
    "## Practical Takeaways",
    "## Key Claims",
    "## Overtraining Continuum",
    "## Sequence of Impairments",
    "## Recovery Time by Muscle Group",
    "## Boundary Conditions",
}


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else text
    return text


def _extract_sections(text: str) -> str:
    lines = text.split("\n")
    output: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        is_heading = stripped.startswith("## ") or stripped.startswith("# ")
        if is_heading:
            capturing = any(h in stripped for h in _KEEP_HEADINGS)
        if capturing:
            output.append(line)
    return "\n".join(output).strip()


def load_vault_research() -> str:
    """Load relevant vault notes and return them as a single formatted string."""
    wiki_dir = settings.vault_path / "wiki"
    if not wiki_dir.exists():
        log.warning("Vault wiki dir not found at %s", wiki_dir)
        return "Vault not available."

    sections: list[str] = []
    for note_name in _VAULT_NOTES:
        path = wiki_dir / note_name
        if not path.exists():
            log.warning("Vault note missing: %s", path)
            continue
        raw = path.read_text(encoding="utf-8")
        content = _strip_frontmatter(raw)
        excerpt = _extract_sections(content) or content[:1500]

        title = note_name.replace(".md", "").replace("-", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        sections.append(f"#### {title}\n\n{excerpt}")

    return "\n\n---\n\n".join(sections)


_VAULT_RESEARCH: str = ""


def get_vault_research() -> str:
    global _VAULT_RESEARCH
    if not _VAULT_RESEARCH:
        _VAULT_RESEARCH = load_vault_research()
    return _VAULT_RESEARCH


# ── Training context builder ──────────────────────────────────────────────────


def build_training_context(conn) -> str:
    """Build the per-request dynamic context string for plan generation.

    Numeric facts come from `compute_daily_state` (single source of truth).
    Exercise lists, working weights, and plan-prior history are queried here
    since they are content the LLM must see verbatim.

    Returns:
        Multi-section text covering readiness, gates, muscle group rest,
        training history, working weights, volume trend, and yesterday's
        adherence (closed-loop feedback).
    """
    today = date.today()
    state = compute_daily_state(conn)
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
        f"+{vol_trend_pct}% (INCREASING — monitor ACWR)" if vol_trend_pct > 15
        else f"{vol_trend_pct}% (stable)" if -10 <= vol_trend_pct <= 15
        else f"{vol_trend_pct}% (decreasing)"
    )

    lines: list[str] = [f"TODAY: {today.isoformat()}\n"]

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

    lines.append("\n## READINESS SNAPSHOT")
    if readiness["score"] is not None:
        adj = " (β-blocker reweighted)" if readiness["beta_blocker_adjusted"] else ""
        lines.append(
            f"- Composite readiness: {readiness['score']:.0f}/100 ({readiness['tier']}){adj}"
        )
    if rec["score"] is not None:
        tier = "🟢 GREEN" if rec["score"] >= 67 else ("🟡 YELLOW" if rec["score"] >= 34 else "🔴 RED")
        lines.append(f"- WHOOP recovery: {rec['score']:.0f} ({tier}) — {rec['score_date']}")
    if rec["hrv_sigma"] is not None:
        lines.append(
            f"- HRV: {rec['hrv_ms']:.1f}ms · 28d {rec['hrv_baseline_28d']:.1f}±{rec['hrv_sd_28d']:.1f}"
            f" · deviation {rec['hrv_sigma']:+.2f}σ"
        )
    if sleep["last_hours"] is not None:
        deep = f", deep {sleep['deep_pct_last']*100:.0f}%" if sleep["deep_pct_last"] else ""
        spo2 = f", SpO₂ {sleep['spo2_avg_last']:.1f}%" if sleep["spo2_avg_last"] else ""
        avg = f" · 7d avg {sleep['avg_7d']:.1f}h" if sleep["avg_7d"] else ""
        lines.append(f"- Sleep last night: {sleep['last_hours']:.1f}h{deep}{spo2}{avg}")
    if load["acwr"] is not None:
        zone = "safe" if 0.8 <= load["acwr"] <= 1.3 else ("⚠ HIGH" if load["acwr"] > 1.3 else "low")
        lines.append(
            f"- ACWR (true Gabbett): {load['acwr']} ({zone}) — "
            f"acute {load['acute_load_7d']:.1f} / chronic {load['chronic_load_28d']:.1f}"
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
    if chk["body_weight_trend_4wk"] is not None:
        lines.append(f"- Body weight trend (4wk): {chk['body_weight_trend_4wk']:+.2f}%")
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
                if comp is not None else "- Adherence: not yet logged"
            )
            if actual_rpe and target_rpe:
                delta = actual_rpe - target_rpe
                lines.append(f"- RPE delivered: {actual_rpe:.1f} vs target {target_rpe:.1f} ({delta:+.1f})")

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

    lines.append(f"\n## TRAINING HISTORY (last 30 days — {len(workout_rows)} sessions)")
    for row in workout_rows[:14]:
        vol_str = f"{row[3] / 1000:.1f} tonnes" if row[3] else "bw/machine"
        rpe_str = f" @RPE {row[4]:.1f}" if row[4] else ""
        ex_preview = (row[1] or "")[:120]
        lines.append(f"- {row[0]}: {row[2]} sets | {vol_str}{rpe_str} | {ex_preview}")

    lines.append(f"\n## WORKING WEIGHTS ({len(ww_rows)} exercises on record)")
    for ex, wkg, src in ww_rows[:40]:
        lbs = round(wkg * 2.20462, 1) if wkg else 0
        lines.append(f"- {ex}: {lbs} lbs ({wkg:.1f} kg) [{src}]")
    if len(ww_rows) > 40:
        lines.append(f"  ... and {len(ww_rows) - 40} more")

    lines.append("\n## TOP EXERCISES (last 90d by frequency)")
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
        GROUP BY modality ORDER BY minutes DESC
        """
    ).fetchall()
    if cardio_rows:
        lines.append(f"\n## CARDIO MIX (last 28 days — {load['cardio_min_28d']} min total, {load['cardio_z2_min_7d']} Z2 min in last 7d)")
        for mod, mins, sess, avg_hr in cardio_rows:
            hr_str = f", avg HR {int(avg_hr)}" if avg_hr else ""
            lines.append(f"- {mod}: {int(mins or 0)} min over {sess} sessions{hr_str}")
    else:
        lines.append(
            "\n## CARDIO MIX (last 28 days): none logged — fat-loss programming should add Z2 + finisher"
        )

    # Goals.
    lines.append("\n## GOALS")
    lines.append("- Primary: get stronger (preserve/build lean mass)")
    lines.append("- Secondary: burn fat (body recomposition)")
    lines.append("- Tactic: heavy compounds for strength, density+supersets+finishers for fat loss")

    if prefs:
        lines.append("\n## EXERCISES TO AVOID/SUBSTITUTE")
        for ex, status, notes in prefs:
            lines.append(f"- {ex} ({status})" + (f": {notes}" if notes else ""))

    return "\n".join(lines)


# ── Validation + auto-regulation gate ────────────────────────────────────────

class GateViolation(ValueError):
    """Raised when a plan violates a hard auto-regulation gate."""


def _exercise_targets_group(exercise: str, group: str) -> bool:
    return muscle_group(exercise) == group


def validate_plan(plan: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """Validate a plan dict against the schema AND the deterministic gates.

    The schema check verifies shape (intensity enum, blocks present, etc.).
    The gate check verifies the plan respects today's hard auto-regulation
    constraints — max intensity, forbidden muscle groups, deload requirement.
    Pass `state` (a `DailyState` dict) to enable gate enforcement; omitting
    it falls back to schema-only validation for backwards compatibility.

    Raises:
        ValueError: on schema violation.
        GateViolation: on auto-regulation gate violation.
    """
    if plan.get("readiness_tier") not in {"green", "yellow", "red"}:
        raise ValueError(f"Invalid readiness_tier: {plan.get('readiness_tier')!r}")
    rec = plan.get("recommendation", {})
    if rec.get("intensity") not in {"high", "moderate", "low", "rest"}:
        raise ValueError(
            f"Invalid intensity: {rec.get('intensity')!r} — must be string enum"
        )
    if not rec.get("focus"):
        raise ValueError("recommendation.focus is empty")
    blocks = plan.get("blocks", [])
    if not blocks:
        raise ValueError("Plan has no blocks")
    for i, block in enumerate(blocks):
        if not block.get("exercises"):
            raise ValueError(f"Block {i} ({block.get('label')!r}) has no exercises")
    if not plan.get("clinical_notes"):
        raise ValueError("clinical_notes is empty — must include medication context")
    if not plan.get("vault_insights"):
        raise ValueError("vault_insights is empty — must cite research")

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
            target_rpe = rec.get("target_rpe", 10)
            if order.index(rec["intensity"]) > order.index("moderate") or target_rpe > 7:
                raise GateViolation(
                    f"Deload required ({gates.get('deload_reason')}) but plan is "
                    f"{rec['intensity']} @ RPE {target_rpe} — must be ≤moderate @ RPE ≤7."
                )
    return True


# ── Persistence ────────────────────────────────────────────────────────────────

async def save_plan(plan: dict[str, Any], source: str = "claude") -> None:
    """Persist a validated plan to workout_plans for today."""
    today = date.today().isoformat()
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
