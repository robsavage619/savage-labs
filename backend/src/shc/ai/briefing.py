from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import anthropic

from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx

log = logging.getLogger(__name__)

MODEL = "claude-opus-4-7"

# Health profile system prompt — stable block, cached across calls.
# Includes all clinically significant context so Claude interprets metrics correctly.
HEALTH_SYSTEM = """\
You are the user's personal health and training advisor. Your role is to \
interpret his biometric data and provide daily coaching guidance. Always factor in \
the following clinical context when analysing any metric.

## Clinical Profile
Male, born May 1986 (38 yo), 6'1" / 239 lbs, BMI 31.3.

### Active medications (metric impact)
- Propranolol 10 mg PRN (beta-blocker for anxiety): artificially suppresses RHR and \
blunts HR response — WHOOP recovery/strain scores are lower than true physiology. \
HRV readings also unreliable when taken while on this drug.
- Lexapro 10 mg daily (SSRI, started Feb 2026): chronically suppresses HRV baseline. \
HRV deviation (σ) from 28-day rolling average is more meaningful than absolute value.
- Fluoxetine 40 mg daily (SSRI): also suppresses HRV.

### Conditions
- GAD + OCD (active): psychological stress spikes may depress HRV/recovery independently \
of physical training load — do not always attribute low HRV to exercise.
- OSA (off CPAP since Apr 2026): sleep quality metrics may be temporarily variable while \
adjusting to CPAP-free breathing. Prioritise sleep duration and deep% over absolute scores.
- Asthma: monitor respiratory rate and SpO2 — any dips below 95% warrant a flag.

### Goals
Primary: strength and hypertrophy (Fitbod resistance training, 3–5 sessions/week).
Secondary: general cardiovascular health, anxiety management through exercise.

### Data limitations
WHOOP data is the primary recovery/HRV source (historical through Feb 2025; current syncs \
live). Fitbod data is the primary training volume source. Apple Health not yet ingested.

## Output format
You MUST return a single JSON object — no prose outside the JSON. Schema:
{
  "training_call": "Push" | "Train" | "Maintain" | "Easy" | "Rest",
  "training_rationale": "<1–2 sentences citing specific metrics>",
  "readiness_headline": "<10 words max — punchy summary of today's state>",
  "coaching_note": "<2–4 sentences of today's actionable coaching. Cite numbers. Be direct.>",
  "flags": ["<flag1>", "<flag2>"],
  "priority_metric": "hrv" | "sleep" | "recovery" | "load" | "none"
}

training_call definitions:
- Push: HRV +1σ above baseline, load optimal (ACWR 0.8–1.3), recovery ≥70
- Train: normal session — metrics nominal, no red flags
- Maintain: suboptimal but not dangerous — keep intensity moderate
- Easy: overreach risk (ACWR >1.3) OR HRV −1.5σ — only Zone 1–2 work
- Rest: ACWR >1.5 OR severe HRV suppression — no structured training
"""

CHAT_SYSTEM = HEALTH_SYSTEM + """

## Chat mode
You are answering a direct question from Rob. Be concise, precise, and cite his \
actual numbers where available. Never hedge excessively — give a clear recommendation. \
Return plain prose (not JSON) in this mode.
"""


def _build_daily_context(conn) -> str:
    today = date.today().isoformat()
    since_28 = (date.today() - timedelta(days=28)).isoformat()
    since_7 = (date.today() - timedelta(days=7)).isoformat()
    since_90 = (date.today() - timedelta(days=90)).isoformat()

    # Latest recovery
    rec = conn.execute(
        "SELECT date, score, hrv, rhr FROM recovery ORDER BY date DESC LIMIT 1"
    ).fetchone()

    # HRV baseline
    hrv_rows = conn.execute(
        "SELECT hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL ORDER BY date",
        {"s": since_28},
    ).fetchall()
    hrv_vals = [r[0] for r in hrv_rows if r[0]]
    import statistics as _st
    hrv_baseline = _st.mean(hrv_vals) if len(hrv_vals) >= 3 else None
    hrv_sd = _st.stdev(hrv_vals) if len(hrv_vals) >= 3 else None
    hrv_sigma = None
    if hrv_baseline and hrv_sd and hrv_sd > 0 and rec and rec[2]:
        hrv_sigma = (rec[2] - hrv_baseline) / hrv_sd

    # ACWR proxy
    rec_rows = conn.execute(
        "SELECT date, score FROM recovery WHERE date >= $s ORDER BY date",
        {"s": since_28},
    ).fetchall()
    since_7_date = date.today() - timedelta(days=7)
    acute_scores = [r[1] for r in rec_rows if r[0] >= since_7_date and r[1]]
    chronic_scores = [r[1] for r in rec_rows if r[1]]
    acute = (100 - _st.mean(acute_scores)) if acute_scores else None
    chronic = (100 - _st.mean(chronic_scores)) if chronic_scores else None
    acwr = round(acute / chronic, 2) if acute and chronic and chronic > 0 else None

    # Sleep 7d avg
    sleep_rows = conn.execute(
        """
        SELECT epoch(ts_out - ts_in) / 3600.0 AS hrs
        FROM sleep WHERE night_date >= $s AND ts_in IS NOT NULL AND ts_out IS NOT NULL
        """,
        {"s": since_7},
    ).fetchall()
    sleep_hrs = [r[0] for r in sleep_rows if r[0] and 2 < r[0] < 14]
    avg_sleep = round(_st.mean(sleep_hrs), 1) if sleep_hrs else None

    # Last training session
    last_train = conn.execute(
        """
        SELECT started_at::DATE AS d,
               COUNT(*) AS sets,
               SUM(CASE WHEN weight_kg IS NOT NULL AND reps IS NOT NULL
                        THEN weight_kg * reps ELSE 0 END) AS vol
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE
        GROUP BY d ORDER BY d DESC LIMIT 1
        """
    ).fetchone()

    lines = [f"## Daily snapshot — {today}"]
    if rec:
        lines.append(f"Recovery score: {round(rec[1]) if rec[1] else '—'}")
        lines.append(f"HRV: {round(rec[2], 1) if rec[2] else '—'} ms")
        lines.append(f"RHR: {rec[3] if rec[3] else '—'} bpm")
    if hrv_baseline:
        lines.append(f"HRV 28d baseline: {round(hrv_baseline, 1)} ms (σ={round(hrv_sd, 1) if hrv_sd else '—'})")
    if hrv_sigma is not None:
        lines.append(f"HRV deviation: {hrv_sigma:+.2f}σ")
    if acwr is not None:
        lines.append(f"ACWR (proxy): {acwr} (acute={round(acute)}, chronic={round(chronic)})")
    if avg_sleep is not None:
        lines.append(f"Avg sleep last 7d: {avg_sleep}h")
    if last_train:
        days_ago = (date.today() - last_train[0]).days if last_train[0] else None
        lines.append(
            f"Last training session: {days_ago}d ago, {last_train[1]} sets, "
            f"{round(last_train[2] / 1000, 1) if last_train[2] else 0}k kg volume"
        )

    return "\n".join(lines)


def generate_briefing() -> dict | None:
    """Generate today's AI briefing. Returns parsed briefing dict or None on failure."""
    if not settings.anthropic_api_key:
        log.warning("anthropic_api_key not set — skipping briefing generation")
        return None

    conn = get_read_conn()
    try:
        context = _build_daily_context(conn)
    finally:
        conn.close()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=[
            {
                "type": "text",
                "text": HEALTH_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": context}],
    )

    raw = ""
    for block in response.content:
        if block.type == "text":
            raw = block.text
            break

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        log.error("briefing JSON parse failed: %s", raw[:200])
        return None

    usage = response.usage
    cost = _estimate_cost(usage)

    return {
        "model": MODEL,
        "training_call": data.get("training_call", "Train"),
        "training_rationale": data.get("training_rationale", ""),
        "readiness_headline": data.get("readiness_headline", ""),
        "coaching_note": data.get("coaching_note", ""),
        "flags": json.dumps(data.get("flags", [])),
        "priority_metric": data.get("priority_metric", "none"),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cost_usd": cost,
    }


def _estimate_cost(usage) -> float:
    # claude-opus-4-7: $5/M input, $25/M output, $0.50/M cache read
    inp = usage.input_tokens or 0
    out = usage.output_tokens or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (inp * 5 + out * 25 + cache_read * 0.5) / 1_000_000


async def store_briefing(briefing: dict) -> None:
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO ai_briefing
                (briefing_date, generated_at, model, training_call, training_rationale,
                 readiness_headline, coaching_note, flags, priority_metric,
                 input_tokens, output_tokens, cache_read_tokens, cost_usd)
            VALUES (today(), now(), $model, $training_call, $training_rationale,
                    $readiness_headline, $coaching_note, $flags, $priority_metric,
                    $input_tokens, $output_tokens, $cache_read_tokens, $cost_usd)
            ON CONFLICT (briefing_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                model = excluded.model,
                training_call = excluded.training_call,
                training_rationale = excluded.training_rationale,
                readiness_headline = excluded.readiness_headline,
                coaching_note = excluded.coaching_note,
                flags = excluded.flags,
                priority_metric = excluded.priority_metric,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                cache_read_tokens = excluded.cache_read_tokens,
                cost_usd = excluded.cost_usd
            """,
            briefing,
        )
    log.info(
        "briefing stored — call=%s cost=$%.4f",
        briefing["training_call"],
        briefing.get("cost_usd", 0),
    )


async def run_daily_briefing() -> None:
    """APScheduler entry point — generate and persist today's briefing."""
    import asyncio

    loop = asyncio.get_running_loop()
    briefing = await loop.run_in_executor(None, generate_briefing)
    if briefing:
        await store_briefing(briefing)
