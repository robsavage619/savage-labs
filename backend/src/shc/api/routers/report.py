"""Unified daily report — one AI report covering all areas.

Collapses the previously separate briefing / health-story / workout / body-comp
loops into a single copy-prompt → Claude → POST-back pass. The prompt instructs the
Claude Code session to pull the aggregated `/api/daily/brief` (DailyState incl. body
composition, vault notes, training) plus the latest physique-critique signal, then
POST one structured report back here. The photo critique stays its own step (it needs
images) but its stored result feeds this report.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shc.db.schema import get_read_conn, write_ctx
from shc.ingest import dupr, hevy, whoop
from shc.metrics import compute_daily_state

router = APIRouter(tags=["daily-report"])
log = logging.getLogger(__name__)

_VALID_CALLS = {"Push", "Train", "Maintain", "Easy", "Rest"}


@router.post("/sync/all")
async def sync_all() -> dict:
    """Force a fresh pull from every connected source before reporting.

    Runs the same WHOOP / Hevy / DUPR syncs the scheduler does, on demand. Each
    source is isolated — one failing (auth, network) never blocks the others; the
    per-source outcome is returned so failures are visible, not silent. Apple
    Health ingests automatically via the file watcher, so it isn't pulled here.
    """
    sources = (("whoop", whoop.sync_all), ("hevy", hevy.sync_workouts), ("dupr", dupr.sync_rating))
    results: dict[str, dict] = {}
    for name, fn in sources:
        try:
            results[name] = {"ok": True, "detail": await fn()}
        except Exception as exc:  # isolate per source — surface, don't abort
            log.warning("sync %s failed: %s", name, exc)
            results[name] = {"ok": False, "error": str(exc)}
    freshness = compute_daily_state(get_read_conn()).get("freshness", {})
    return {"results": results, "freshness": freshness}

_PROMPT = """\
Generate Rob's COMPLETE daily report in one pass. This is the SINGLE report and must
carry the FULL depth and research grounding — it replaces the old briefing,
health-story, workout, and analytics dashboard. Be thorough and analytical, never thin.

## Sync first, then pull ALL of these
1. POST http://127.0.0.1:8000/api/sync/all — refresh WHOOP / Hevy / DUPR. Note any
   source returning `ok: false`.
2. GET http://127.0.0.1:8000/api/daily/brief — DailyState (full metric set below),
   recent training, AND the curated vault research notes. Single source of numbers.
3. GET http://127.0.0.1:8000/api/workout/context — TIMING-AWARE workout plan (if Rob
   trained today it auto-plans the NEXT session). Use for the training section.
4. GET http://127.0.0.1:8000/api/stats/summary — ACWR, RHR elevation, recovery-trend
   slope, sleep avg/consistency/debt analytics.
5. GET http://127.0.0.1:8000/api/insights AND /api/insights/correlations — detected
   patterns.
6. GET http://127.0.0.1:8000/api/progress-photos/critique — physique verdict (null → say so).

## Use the FULL metric set — do not cherry-pick
Recovery: HRV + **hrv_sigma** (σ vs 28d baseline), RHR + elevation%, skin-temp delta
(already °F), **respiratory_rate_delta**, SpO2, calibration flag. Sleep: deep%/**REM%**/
**efficiency%**/consistency/performance, the **sleep-need breakdown** (base/debt/strain/
nap), debt_7d, midpoint + midpoint variability. Training load: ACWR (+ acute_load_7d /
chronic_load_28d), days-since legs/push/pull, push:pull balance, **pickleball_min_7d/28d**,
**cardio zone minutes (z0–z5)**, max HR. Plus readiness (weighted, β-blocker), check-in
subjectives, gates, body_composition, freshness.

If any source returned `ok: false`, any metric is null, or the photo critique is null,
SAY SO in the relevant section — never silently fabricate a number around missing data.

## Ground it in the research — DO NOT lose this
- USE the vault notes from /daily/brief. In the prose, cite by CONCEPT (e.g. "the
  research on effective reps"), and put every vault filename you drew on in the
  top-level `sources` array — those render as Obsidian-logo citations in the UI.
  These are Rob's curated evidence — never give generic advice that ignores them.
- Honor each metric's research model:
  • HRV → interpret via **hrv_sigma**, not raw ms alone.
  • HRmax → max_hr_measured if present, else **Tanaka (208−0.7·age)** — NEVER 220−age.
  • Respiratory rate → **Bourdillon** illness sentinel (+~1 bpm = flag).
  • Deep sleep → **OSA-aware**: deep% weighs more than raw duration.
  • ACWR → true **Gabbett** acute/chronic; >1.3 = reduce volume; >1.5 = cap LOW; >1.65 = rest.
  • Readiness → weighted composite, β-blocker-reweighted when propranolol taken.

## Timing awareness — the API decides the MODE (do NOT re-infer it)
`/api/daily/brief` returns an authoritative top-level **`mode`** and **`planning_date`**
(computed the same way the workout planner decides). Use them verbatim — don't derive
your own from `days_since_last`, or you may disagree with the plan the context built.
- `mode = "post_workout"` → Rob already trained today. Write a POST-WORKOUT BRIEF: review
  what he did today (sets/exercises, how it tracked vs plan), today's recovery, and the
  NEXT session plan (for `planning_date`). Do NOT just say "Rest".
- `mode = "pre_workout"` → plan today's session (`planning_date` = today).
Copy `mode` into the top-level field and make the Readiness headline reflect it.

## Generate the actual workout (not just prose)
Build the structured workout for `planning_date` and **POST it to
http://127.0.0.1:8000/api/workout/plan** with
`{"plan": <plan>, "source": "claude", "push_to_hevy": false, "plan_date": "<planning_date>"}`.
This makes the session real and ready for the one-tap Hevy push — don't leave it as
narrative only. The server validates the plan and rejects malformed shapes, so use this
EXACT schema (field names are strict — `label` not `name`, `cooldown` is a plain string):

```json
{
  "readiness_tier": "green | yellow | red",
  "recommendation": {"intensity": "high | moderate | low | rest", "focus": "<one line>"},
  "blocks": [
    {"label": "<block name>", "exercises": [
      {"name": "<EXACT Hevy exercise name>", "sets": 3, "reps": "10",
       "weight_lbs": 130, "rpe_target": 7, "rest_seconds": 150, "notes": "<cue>"}
    ]}
  ],
  "cooldown": "<plain string>",
  "clinical_notes": "<med/gate context — required, non-empty>",
  "vault_insights": ["effective-reps-hypertrophy.md", "..."]
}
```
Hard constraints from `/api/workout/context`: `recommendation.intensity` must not exceed
the gate's max intensity; every loaded exercise must stay under the e1RM load ceiling;
respect forbidden muscle groups; every `vault_insights` filename must be a real catalog
note; `rest_seconds` is required on every exercise.

## Write ONE deep report (sections in order)
- **Readiness** — recovery/sleep/HRV/RHR/resp-rate/load, what each signal *means* today.
- **Metrics & progression** — interpret the stats/summary analytics (ACWR trend, RHR vs
  baseline, recovery slope, sleep avg/consistency/debt). The analytical depth.
- **Patterns** — noteworthy items from /insights + correlations (omit if none).
- **Training call + next session** — call (Push/Train/Maintain/Easy/Rest) + the session
  from workout/context (timing-aware), respecting gates. Rob is 40 and training to peak
  athletic form — not maintaining, PEAKING. Goal: 4.5 → 5.0 DUPR doubles pickleball by
  end of 2026, concurrent strength + size (not generic recomp). He refuses to let age set
  the ceiling; your job is to design sessions that honor that. Push hard when gates allow.
  Cite vault notes.
- **Health story** — knowledgeable-friend narrative tying it together.
- **Body composition** — waist:shoulder / waist:hip + critique verdict vs lean-out-keep-size.
  No change claims the gated trend doesn't support; no body-fat %.

## Depth — this is the whole point, do NOT write thin
Each section must REASON, not just list. For every signal: say what it means, WHY it
matters today, how it connects to the others, and the so-what. Name tensions explicitly
(e.g. "green recovery but ACWR says overload — here's how I'd resolve it"). A bare bullet
of numbers is a failure — lead with interpretation and back it with the number, not the
reverse. Earlier reports were 2-4 substantive sentences (or a short lead paragraph +
explained bullets) per section; match that. Bullets are scaffolding for analysis, never a
substitute for it. The body-comp and training sections especially should explain mechanism
and trade-offs, citing the vault research by concept.

Format in markdown (`**bold**` key numbers, occasional `##` subheads, bullets where they
genuinely aid structure) but prioritize reasoning density over scannability. °F and lbs.
Direct and analytical, never flattering or padded.

## Return — POST to http://127.0.0.1:8000/api/daily/report
{"mode": "<pre_workout|post_workout>",
 "training_call": "<Push|Train|Maintain|Easy|Rest>",
 "readiness_headline": "<one line, reflects the mode>",
 "sections": [{"title": "Readiness", "body_md": "..."},
              {"title": "Metrics & progression", "body_md": "..."},
              {"title": "Patterns", "body_md": "..."},
              {"title": "Today's session" (post_workout) OR "Training call + session" (pre_workout), "body_md": "..."},
              {"title": "Health story", "body_md": "..."},
              {"title": "Body composition", "body_md": "..."}],
 "sources": ["effective-reps-hypertrophy.md", "..."],
 "model": "claude"}

Remember: also POST the structured workout to /api/workout/plan (above).
"""


@router.get("/daily/report/prompt")
async def daily_report_prompt() -> dict:
    """Return the single prompt that generates the whole daily report."""
    return {"prompt": _PROMPT}


class SectionIn(BaseModel):
    title: str
    body_md: str


class DailyReportSubmission(BaseModel):
    training_call: str | None = None
    readiness_headline: str | None = None
    sections: list[SectionIn]
    sources: list[str] = []  # vault filenames cited (rendered as Obsidian tags)
    mode: str | None = None  # 'pre_workout' | 'post_workout'
    model: str = "claude"


@router.post("/daily/report")
async def submit_daily_report(body: DailyReportSubmission) -> dict:
    """Persist a Claude-generated unified daily report (one row per day)."""
    if body.training_call and body.training_call not in _VALID_CALLS:
        raise HTTPException(422, f"training_call must be one of {sorted(_VALID_CALLS)}")

    # Drop hallucinated citations — only keep filenames that exist in the vault
    # catalogue, so a fabricated source can't render as a real Obsidian tag.
    from shc.ai.vault import valid_citation_filenames

    allowed = valid_citation_filenames()
    sources, unknown = [], []
    for s in body.sources:
        (sources if s in allowed else unknown).append(s)
    if unknown:
        log.warning("daily report dropped %d unknown citation(s): %s", len(unknown), unknown)

    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO ai_daily_report
                (report_date, generated_at, model, training_call, readiness_headline,
                 sections, sources, mode)
            VALUES (today(), now(), $model, $call, $headline, $sections, $sources, $mode)
            ON CONFLICT (report_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                model = excluded.model,
                training_call = excluded.training_call,
                readiness_headline = excluded.readiness_headline,
                sections = excluded.sections,
                sources = excluded.sources,
                mode = excluded.mode
            """,
            {
                "model": body.model,
                "call": body.training_call,
                "headline": body.readiness_headline,
                "sections": json.dumps([s.model_dump() for s in body.sections]),
                "sources": json.dumps(sources),
                "mode": body.mode,
            },
        )
    log.info(
        "daily report stored — mode=%s call=%s sections=%d sources=%d",
        body.mode, body.training_call, len(body.sections), len(body.sources),
    )
    return {"status": "ok"}


@router.get("/daily/report")
async def latest_daily_report() -> dict:
    """Return the most recent unified daily report."""
    row = get_read_conn().execute(
        "SELECT report_date, generated_at, model, training_call, readiness_headline, "
        "sections, sources, mode "
        "FROM ai_daily_report ORDER BY report_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"report": None}
    return {
        "report": {
            "report_date": str(row[0]),
            "generated_at": str(row[1]),
            "model": row[2],
            "training_call": row[3],
            "readiness_headline": row[4],
            "sections": json.loads(row[5]) if row[5] else [],
            "sources": json.loads(row[6]) if row[6] else [],
            "mode": row[7],
        }
    }
