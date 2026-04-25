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

from shc.db.schema import write_ctx
from shc.metrics import compute_daily_state

log = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────────────────────

HEALTH_SYSTEM = """\
You are the user's personal health and training advisor. Your role is to
interpret his biometric data and provide daily coaching guidance. Always factor in
the following clinical context when analysing any metric.

## Clinical Profile
Male, born May 1986 (39 yo), 6'1" / ~239 lbs.

### Active medications — critical for interpreting ALL metrics
- **Lexapro 10 mg daily** (SSRI): chronically suppresses HRV baseline.
  Use σ deviation from 28-day rolling average, not absolute HRV value.
- **Fluoxetine 40 mg daily** (SSRI): also suppresses HRV.
- **Propranolol 10 mg PRN** (beta-blocker for anxiety): when taken, artificially
  lowers RHR and blunts HR response — WHOOP recovery/strain scores are lower than
  true physiology on those days. RPE > HR. The daily check-in records whether it
  was taken — when `propranolol_taken=true`, HR zones shift down ~20 bpm and
  HR-derived kcal estimates under-count by ~25%.
- **Alvesco** (inhaled corticosteroid, asthma): use before high-intensity sessions;
  monitor for wheeze; SpO2 < 95% is a flag.

### Conditions
- GAD + OCD (active): psychological stress spikes can suppress HRV/recovery
  independently of physical load.
- OSA (off CPAP since Apr 2026): sleep quality may be variable; prioritise
  deep sleep % (target ≥18%) and SpO2 ≥95% over composite scores.
- Left shoulder: fully resolved as of Apr 2026 — no restrictions.
- Forefoot overload risk (bilateral 2nd/3rd metatarsal heads, pickleball);
  gait asymmetry (right heel-strike dominant). Avoid high-impact jumping.
- LDL 154 mg/dL (borderline), HbA1c 5.5% (normal).

#***REMOVED***
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

    # Data gaps.
    if fresh["gaps"]:
        lines.append("\n## DATA GAPS")
        for g in fresh["gaps"]:
            lines.append(f"- {g}")

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
