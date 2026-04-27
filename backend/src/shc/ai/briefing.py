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

from shc.ai.workout_planner import load_vault_research
from shc.db.schema import write_ctx
from shc.metrics import compute_daily_state

log = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────────────────────

HEALTH_SYSTEM = """\
You are the user's personal health and training advisor. Your role is to
interpret his biometric data and provide daily coaching guidance.

The patient-specific clinical context (active medications, active conditions,
recent labs, age/weight) is provided in the dynamic live-data block below this
prompt — read it there, do not assume it from prior knowledge. This system
prompt only encodes drug-class interpretation rules and coaching principles
that are stable over time.

## Drug-class interpretation rules (apply when the live data shows a member of the class)
- **SSRIs**: chronically suppress HRV
  baseline. Always interpret HRV as σ deviation from a 28-day rolling mean,
  never as an absolute number.
- **Beta-blockers**: artificially lower RHR and blunt HR
  response. WHOOP recovery/strain are lower than true physiology on dosed
  days. Use RPE > HR. The daily check-in's `propranolol_taken` flag drives
  the `hr_zone_shift_bpm` and `kcal_multiplier` values you see in the gates.
- **Inhaled corticosteroids**: use before
  high-intensity sessions in patients with asthma; SpO2 < 95% is a flag.

***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***

***REMOVED***
***REMOVED***
***REMOVED***
## Personal context

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

CHAT_SYSTEM = HEALTH_SYSTEM + """
## Chat mode
Answer direct questions. Be concise and cite his actual numbers. Never hedge
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
        lines.append(f"Skin temp: {rec['skin_temp']:.2f}°C (Δ {rec['skin_temp_delta']:+.2f}°C vs 28d)")

    # Sleep.
    if sleep["last_hours"] is not None:
        deep = f", deep {sleep['deep_pct_last']*100:.0f}%" if sleep["deep_pct_last"] else ""
        spo2 = f", SpO₂ {sleep['spo2_avg_last']:.1f}%" if sleep["spo2_avg_last"] else ""
        avg = f" · 7d avg {sleep['avg_7d']:.1f}h" if sleep["avg_7d"] else ""
        lines.append(f"Sleep: {sleep['last_hours']:.1f}h{deep}{spo2}{avg}")

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

    vault = load_vault_research(state)
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
