from __future__ import annotations

"""Daily briefing context builder and persistence helpers.

Generation is chat-driven — Claude produces the briefing in the chat interface,
then POSTs it to /api/briefing.  This module provides:

  1. HEALTH_SYSTEM / CHAT_SYSTEM — system prompts for the frontend chat.
  2. build_daily_context() — per-request dynamic health snapshot injected
     into every chat message so Claude always has live data.
  3. store_briefing() — persists a generated briefing dict.

All numeric facts in `build_daily_context` are derived from the canonical
`shc.metrics.DailyState`. Adding a new metric here means adding it once in
`shc/metrics.py` and rendering it as text here — never recomputing.
"""

import json
import logging
from datetime import date

from shc.ai._personal_context import load_personal_context
from shc.ai.lab_findings import lab_findings_section
from shc.ai.workout_planner import load_vault_research
from shc.db.schema import write_ctx
from shc.metrics import compute_daily_state

log = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────────────────────

def _build_health_system() -> str:
    personal = load_personal_context()
    personal_block = f"\n{personal}\n" if personal else ""
    return f"""\
You are the user's personal health and training advisor. Your role is to
interpret biometric data and provide daily coaching guidance.

The patient-specific clinical context (active medications, active conditions,
recent labs, age/weight) is provided in the dynamic live-data block below this
prompt — read it there, do not assume it from prior knowledge. This system
prompt only encodes drug-class interpretation rules, personal context, and
coaching principles that are stable over time.

## Drug-class interpretation rules (apply when the live data shows a member of the class)
- **SSRIs**: chronically suppress HRV baseline. Always interpret HRV as σ
  deviation from a 28-day rolling mean, never as an absolute number.
- **Beta-blockers**: artificially lower RHR and blunt HR response. WHOOP
  recovery/strain are lower than true physiology on dosed days. Use RPE > HR.
  The daily check-in's `propranolol_taken` flag drives the `hr_zone_shift_bpm`
  and `kcal_multiplier` values you see in the gates.
- **Inhaled corticosteroids**: use before high-intensity sessions in patients
  with asthma; SpO2 < 95% is a flag.
{personal_block}
## Coaching principles (always apply)
1. HRV interpretation: σ deviation from 28d rolling mean. Green ≥ −0.5σ;
   Yellow −1.5 to −0.5σ; Red < −1.5σ.
2. ACWR safe zone: 0.8–1.3 (true Gabbett — acute training load ÷ chronic
   load, NOT a recovery-score ratio). Above 1.3 → reduce volume. Above 1.5 → rest only.
3. Muscle group recovery: 48h minimum, 72h preferred for compound lower body.
4. Data gaps > 3 days: reduce reliance on that metric, note it explicitly.
5. Exercise naming: use names from the user's Hevy history, not generic terms.
6. Auto-regulation gates (in `daily_state.gates`) are HARD constraints — the
   plan must respect `max_intensity` and `forbid_muscle_groups`.
"""


HEALTH_SYSTEM = _build_health_system()

CHAT_SYSTEM = HEALTH_SYSTEM + """
## Chat mode
Answer direct questions. Be concise and cite actual numbers. Never hedge
excessively — give a clear recommendation. Return plain prose (not JSON).

## Live data
The current training context is injected at the end of the system prompt on every
request — you always have today's metrics, recent sessions, and working weights.
"""


# ── Clinical context (live from DB) ──────────────────────────────────────────

_RESOLVED_STATUSES = {"resolved", "inactive", "remission"}


def build_clinical_context(conn) -> str:
    """Build a live clinical snapshot from the bitemporal source-of-truth tables.

    Pulls active medications (started ≤ today, not yet stopped, record valid),
    active conditions (status not in resolved/inactive/remission), and the most
    recent lab value per analyte from the last 12 months.

    Returns a markdown block. Empty string if all three queries return nothing,
    so the caller can decide whether to skip the section entirely.
    """
    today = date.today().isoformat()

    meds = conn.execute(
        """
        SELECT name, dose, frequency, started
        FROM medications
        WHERE valid_to IS NULL
          AND (started IS NULL OR started <= $today)
          AND (stopped IS NULL OR stopped > $today)
        ORDER BY started DESC NULLS LAST
        """,
        {"today": today},
    ).fetchall()

    conditions = conn.execute(
        """
        SELECT name, status, onset
        FROM conditions
        WHERE valid_to IS NULL
          AND (status IS NULL OR LOWER(status) NOT IN ('resolved', 'inactive', 'remission'))
        ORDER BY onset DESC NULLS LAST
        """
    ).fetchall()

    labs = conn.execute(
        """
        SELECT name, value, unit, ref_low, ref_high, collected_at
        FROM (
            SELECT name, value, unit, ref_low, ref_high, collected_at,
                   ROW_NUMBER() OVER (PARTITION BY name ORDER BY collected_at DESC) AS rn
            FROM labs
            WHERE collected_at IS NOT NULL
              AND collected_at >= (current_date - INTERVAL '365 days')
        )
        WHERE rn = 1
        ORDER BY collected_at DESC
        LIMIT 20
        """
    ).fetchall()

    if not (meds or conditions or labs):
        return ""

    lines: list[str] = ["## CLINICAL PROFILE (live from DB)"]

    if meds:
        lines.append("\n### Active medications")
        for name, dose, freq, started in meds:
            parts = [name]
            if dose:
                parts.append(dose)
            if freq:
                parts.append(freq)
            since = f" — since {started}" if started else ""
            lines.append(f"- {' '.join(parts)}{since}")
    else:
        lines.append("\n### Active medications: none on record")

    if conditions:
        lines.append("\n### Active conditions")
        for name, status, onset in conditions:
            status_str = f" ({status})" if status else ""
            onset_str = f", onset {onset}" if onset else ""
            lines.append(f"- {name}{status_str}{onset_str}")
    else:
        lines.append("\n### Active conditions: none on record")

    if labs:
        lines.append("\n### Recent labs (most recent value per analyte, last 12 months)")
        for name, value, unit, ref_low, ref_high, collected_at in labs:
            v_str = f"{value:g}" if value is not None else "—"
            unit_str = f" {unit}" if unit else ""
            range_str = ""
            flag = ""
            if ref_low is not None and ref_high is not None:
                range_str = f" (ref {ref_low:g}–{ref_high:g})"
                if value is not None:
                    if value < ref_low:
                        flag = " ⬇ LOW"
                    elif value > ref_high:
                        flag = " ⬆ HIGH"
            elif ref_high is not None and value is not None:
                range_str = f" (ref ≤{ref_high:g})"
                if value > ref_high:
                    flag = " ⬆ HIGH"
            date_str = str(collected_at)[:10]
            lines.append(f"- {name}: {v_str}{unit_str}{range_str}{flag} — {date_str}")

    return "\n".join(lines)


# ── Context builder ───────────────────────────────────────────────────────────

def build_daily_context(conn) -> str:
    """Build a dynamic daily health + training snapshot from the live DB.

    All numeric values are pulled from `compute_daily_state` so the chat
    advisor sees the same readiness score, ACWR, and gates that the dashboard
    and the workout planner see.

    Args:
        conn: An open DuckDB read connection.
    """
    state = compute_daily_state(conn)
    rec = state["recovery"]
    sleep = state["sleep"]
    load = state["training_load"]
    chk = state["checkin"]
    readiness = state["readiness"]
    gates = state["gates"]
    fresh = state["freshness"]

    lines: list[str] = [f"\n## Live data — {state['as_of']}"]

    clinical = build_clinical_context(conn)
    if clinical:
        lines.append("\n" + clinical)

    # Readiness composite — single canonical number.
    if readiness["score"] is not None:
        tier = readiness["tier"]
        emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(tier, "")
        adj = " (β-blocker reweighted)" if readiness["beta_blocker_adjusted"] else ""
        lines.append(
            f"Readiness: {readiness['score']:.0f}/100 {emoji} {tier}{adj}"
        )

    # Recovery vitals.
    if rec["score"] is not None:
        hrv_str = f"{rec['hrv_ms']:.1f} ms" if rec["hrv_ms"] else "—"
        rhr_str = f"{rec['rhr']} bpm" if rec["rhr"] else "—"
        lines.append(f"WHOOP recovery: {rec['score']:.0f}/100 · HRV {hrv_str} · RHR {rhr_str}")
    if rec["hrv_sigma"] is not None:
        lines.append(
            f"HRV deviation: {rec['hrv_sigma']:+.2f}σ "
            f"(28d baseline {rec['hrv_baseline_28d']:.1f} ± {rec['hrv_sd_28d']:.1f} ms)"
        )
    if rec["skin_temp_delta"] is not None:
        temp_f = rec["skin_temp"] * 9 / 5 + 32
        delta_f = rec["skin_temp_delta"] * 9 / 5
        lines.append(f"Skin temp: {temp_f:.1f}°F (Δ {delta_f:+.1f}°F vs 28d)")
    if rec.get("spo2_pct") is not None:
        lines.append(f"Overnight SpO₂ (recovery): {rec['spo2_pct']:.1f}%")
    if rec.get("respiratory_rate_delta") is not None and rec.get("respiratory_rate_baseline_28d") is not None:
        delta = rec["respiratory_rate_delta"]
        flag = " ⚠ illness sentinel" if delta >= 1.0 else ""
        lines.append(
            f"Resp rate Δ {delta:+.2f} bpm vs 28d baseline "
            f"({rec['respiratory_rate_baseline_28d']:.2f} bpm){flag}"
        )
    if rec.get("user_calibrating"):
        lines.append("⚠ WHOOP user_calibrating=true — recovery score may be unreliable")

    # Sleep — full architecture, not just hours.
    if sleep["last_hours"] is not None:
        parts = [f"{sleep['last_hours']:.1f}h asleep"]
        if sleep.get("in_bed_min_last"):
            parts.append(f"{sleep['in_bed_min_last']/60:.1f}h in bed")
        if sleep.get("efficiency_pct_last") is not None:
            parts.append(f"efficiency {sleep['efficiency_pct_last']:.0f}%")
        if sleep.get("performance_pct_last") is not None:
            parts.append(f"performance {sleep['performance_pct_last']:.0f}%")
        if sleep.get("consistency_pct_last") is not None:
            parts.append(f"consistency {sleep['consistency_pct_last']:.0f}%")
        lines.append(f"Sleep: {' · '.join(parts)}")

        # Stage architecture (deep / REM / light / awake) in minutes + pct.
        stage_parts: list[str] = []
        if sleep.get("deep_min_last") and sleep.get("deep_pct_last") is not None:
            stage_parts.append(f"deep {sleep['deep_min_last']:.0f}m ({sleep['deep_pct_last']*100:.0f}%)")
        if sleep.get("rem_min_last") and sleep.get("rem_pct_last") is not None:
            stage_parts.append(f"REM {sleep['rem_min_last']:.0f}m ({sleep['rem_pct_last']*100:.0f}%)")
        if sleep.get("light_min_last"):
            stage_parts.append(f"light {sleep['light_min_last']:.0f}m")
        if sleep.get("awake_min_last"):
            stage_parts.append(f"awake {sleep['awake_min_last']:.0f}m")
        if stage_parts:
            lines.append(f"  Stages: {', '.join(stage_parts)}")

        extras: list[str] = []
        if sleep.get("sleep_cycle_count_last"):
            extras.append(f"{sleep['sleep_cycle_count_last']} cycles")
        if sleep.get("disturbance_count_last") is not None:
            extras.append(f"{sleep['disturbance_count_last']} disturbances")
        if sleep.get("respiratory_rate_last"):
            extras.append(f"resp rate {sleep['respiratory_rate_last']:.1f} bpm")
        if sleep.get("spo2_avg_last"):
            extras.append(f"SpO₂ {sleep['spo2_avg_last']:.1f}%")
        if extras:
            lines.append(f"  Quality: {', '.join(extras)}")

        # Sleep need attribution (baseline + debt + strain - nap_credit).
        need_parts: list[str] = []
        if sleep.get("sleep_need_baseline_min_last"):
            need_parts.append(f"baseline {sleep['sleep_need_baseline_min_last']/60:.1f}h")
        if sleep.get("sleep_need_debt_min_last"):
            need_parts.append(f"+debt {sleep['sleep_need_debt_min_last']/60:.1f}h")
        if sleep.get("sleep_need_strain_min_last"):
            need_parts.append(f"+strain {sleep['sleep_need_strain_min_last']/60:.1f}h")
        if sleep.get("sleep_need_nap_min_last"):
            need_parts.append(f"−nap {sleep['sleep_need_nap_min_last']/60:.1f}h")
        if need_parts and sleep.get("sleep_needed_min_last"):
            lines.append(
                f"  Sleep need: {sleep['sleep_needed_min_last']/60:.1f}h "
                f"= {' '.join(need_parts)}"
            )

        if sleep.get("avg_7d"):
            lines.append(f"  7d avg: {sleep['avg_7d']:.1f}h")

    # Training load — TRUE ACWR from session strain.
    if load["acwr"] is not None:
        zone = "safe" if 0.8 <= load["acwr"] <= 1.3 else ("⚠ HIGH" if load["acwr"] > 1.3 else "low")
        lines.append(
            f"ACWR (true Gabbett): {load['acwr']} ({zone}) — "
            f"acute {load['acute_load_7d']:.1f} / chronic {load['chronic_load_28d']:.1f}"
        )
    if load["last_session_date"]:
        lines.append(
            f"Last session: {load['days_since_last']}d ago "
            f"(legs {load['days_since_legs']}d, push {load['days_since_push']}d, pull {load['days_since_pull']}d)"
        )
    # Max HR — surface measured value so the LLM uses correct zones.
    if load.get("max_hr_measured"):
        formula = (
            f" (vs Tanaka {load['max_hr_tanaka']})" if load.get("max_hr_tanaka") else ""
        )
        lines.append(f"Max HR (WHOOP-measured): {load['max_hr_measured']} bpm{formula}")
    # Pickleball volume — primary sport for the 4.5→5.0 climb. Surfaced so
    # the planner frames lifting as court-power transfer when sport vol is high.
    pb7 = load.get("pickleball_min_7d") or 0
    pb28 = load.get("pickleball_min_28d") or 0
    if pb7 or pb28:
        lines.append(
            f"Pickleball volume: {pb7}m last 7d · {pb28}m last 28d "
            f"(primary sport for 4.5→5.0 climb)"
        )

    # Cardio HR zone distribution (last 7 days, WHOOP-authoritative).
    zones = load.get("cardio_zone_min_7d") or {}
    if zones and any(zones.values()):
        z_total = sum(zones.values())
        if z_total > 0:
            parts = [
                f"{k.upper()} {int(v)}m ({v/z_total*100:.0f}%)"
                for k, v in sorted(zones.items())
                if v > 0
            ]
            lines.append(f"HR zone mix (7d, {int(z_total)}m total): {', '.join(parts)}")

    if load["push_pull_ratio_28d"] is not None:
        lines.append(
            f"28d sets: push {load['push_sets_28d']} | pull {load['pull_sets_28d']} | "
            f"legs {load['legs_sets_28d']} (P:P ratio {load['push_pull_ratio_28d']:.2f})"
        )

    # Daily check-in (only what's filled in).
    chk_parts: list[str] = []
    if chk["propranolol_taken"] is True:
        chk_parts.append("propranolol TAKEN today")
    elif chk["propranolol_taken"] is False:
        chk_parts.append("no propranolol today")
    if chk["soreness_overall"] is not None:
        chk_parts.append(f"soreness {chk['soreness_overall']}/10")
    if chk["sleep_quality"] is not None:
        chk_parts.append(f"sleep quality {chk['sleep_quality']}/10")
    if chk["energy"] is not None:
        chk_parts.append(f"energy {chk['energy']}/10")
    if chk["body_weight_kg"] is not None:
        chk_parts.append(f"weight {chk['body_weight_kg']:.1f} kg")
    if chk["illness_flag"]:
        chk_parts.append("ILLNESS flag")
    if chk["travel_flag"]:
        chk_parts.append("travel flag")
    if chk_parts:
        lines.append(f"Today's check-in: {' · '.join(chk_parts)}")
    sore_map = chk.get("muscle_soreness") or {}
    if sore_map:
        sev_label = {1: "mild", 2: "moderate", 3: "acute"}
        items = [
            f"{m.replace('_', ' ')} {sev_label.get(int(s), str(s))}"
            for m, s in sorted(sore_map.items(), key=lambda kv: -kv[1])
        ]
        lines.append(f"Muscle soreness (body diagram): {', '.join(items)}")
    if chk["body_weight_trend_4wk"] is not None:
        lines.append(f"Body weight trend (4wk): {chk['body_weight_trend_4wk']:+.2f}%")

    # Auto-regulation gates — surface to the LLM so it knows the constraints.
    if gates["reasons"]:
        lines.append("\n## AUTO-REG GATES (must respect)")
        lines.append(f"Max intensity allowed: {gates['max_intensity'].upper()}")
        if gates["forbid_muscle_groups"]:
            lines.append(f"Forbidden muscle groups today: {', '.join(gates['forbid_muscle_groups'])}")
        if gates["deload_required"]:
            lines.append(f"DELOAD WEEK REQUIRED: {gates['deload_reason']}")
        if gates["hr_zone_shift_bpm"]:
            lines.append(
                f"HR zones: shift −{gates['hr_zone_shift_bpm']} bpm (propranolol day)"
            )
        for r in gates["reasons"]:
            lines.append(f"- {r}")

    # Data ages — concrete day counts so the LLM can weigh staleness itself.
    age_parts: list[str] = []
    if fresh["whoop_age_days"] is not None:
        age_parts.append(f"WHOOP {fresh['whoop_age_days']}d")
    if fresh["sleep_age_days"] is not None:
        age_parts.append(f"sleep {fresh['sleep_age_days']}d")
    if fresh["hevy_age_days"] is not None:
        age_parts.append(f"Hevy {fresh['hevy_age_days']}d")
    if fresh["cardio_age_days"] is not None:
        age_parts.append(f"cardio {fresh['cardio_age_days']}d")
    if age_parts:
        lines.append("\n## DATA AGES (days since most recent record)")
        lines.append("- " + " · ".join(age_parts))

    # Data gaps (>2d staleness flagged by metrics layer).
    if fresh["gaps"]:
        lines.append("\n## DATA GAPS")
        for g in fresh["gaps"]:
            lines.append(f"- {g}")

    lab = lab_findings_section(conn)
    if lab:
        lines.append("\n" + lab)

    # Retrieval needs hints + extra signals or all hint-based scoring is dead
    # and the briefing is grounded in a near-constant pinned set regardless of
    # today's state. Mirror the planner's derivation from load + soreness.
    extra: set[str] = set()
    ratio = load.get("push_pull_ratio_28d")
    if ratio is not None and (ratio > 1.3 or ratio < 0.75):
        extra.add("push_pull_imbalance")
    hints: list[str] = ["hypertrophy", "strength", "progressive overload", "periodization"]
    if ratio is not None and ratio > 1.3:
        hints += ["pull", "posterior chain", "row", "lat"]
    elif ratio is not None and ratio < 0.75:
        hints += ["push", "chest", "press", "anterior"]
    hints.extend(m for m, sev in (chk.get("muscle_soreness") or {}).items() if (sev or 0) >= 2)

    vault = load_vault_research(state, extra_signals=extra, keyword_hints=hints)
    if vault:
        lines.append("\n" + vault)

    return "\n".join(lines)


# ── Persistence ────────────────────────────────────────────────────────────────

async def store_briefing(briefing: dict) -> None:
    """Persist a briefing dict generated by Claude in chat."""
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO ai_briefing
                (briefing_date, generated_at, model, training_call, training_rationale,
                 readiness_headline, coaching_note, flags, priority_metric,
                 input_tokens, output_tokens, cache_read_tokens, cost_usd)
            VALUES (today(), now(), $model, $training_call, $training_rationale,
                    $readiness_headline, $coaching_note, $flags, $priority_metric,
                    0, 0, 0, 0)
            ON CONFLICT (briefing_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                model = excluded.model,
                training_call = excluded.training_call,
                training_rationale = excluded.training_rationale,
                readiness_headline = excluded.readiness_headline,
                coaching_note = excluded.coaching_note,
                flags = excluded.flags,
                priority_metric = excluded.priority_metric
            """,
            {
                "model": briefing.get("model", "claude"),
                "training_call": briefing["training_call"],
                "training_rationale": briefing.get("training_rationale", ""),
                "readiness_headline": briefing.get("readiness_headline", ""),
                "coaching_note": briefing.get("coaching_note", ""),
                "flags": json.dumps(briefing.get("flags", [])),
                "priority_metric": briefing.get("priority_metric", "none"),
            },
        )
    log.info("briefing stored — call=%s", briefing["training_call"])
