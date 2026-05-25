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
Recovery: HRV + **hrv_sigma** (σ vs 28d baseline), RHR + elevation%, skin-temp delta,
**respiratory_rate_delta**, calibration flag. Sleep: deep%/REM/efficiency/consistency,
the **sleep-need breakdown** (base/debt/strain/nap), midpoint. Training load: ACWR,
days-since legs/push/pull, push:pull balance, zone minutes, max HR. Plus readiness
(weighted, β-blocker), check-in subjectives, gates, body_composition, freshness.

## Ground it in the research — DO NOT lose this
- USE the vault notes from /daily/brief and **cite them by filename** when an
  interpretation or recommendation rests on them (e.g. effective-reps-hypertrophy.md).
  These are Rob's curated evidence — never give generic advice that ignores them.
- Honor each metric's research model:
  • HRV → interpret via **hrv_sigma**, not raw ms alone.
  • HRmax → max_hr_measured if present, else **Tanaka (208−0.7·age)** — NEVER 220−age.
  • Respiratory rate → **Bourdillon** illness sentinel (+~1 bpm = flag).
  • Deep sleep → **OSA-aware**: deep% weighs more than raw duration.
  • ACWR → true **Gabbett** acute/chronic; >1.5 = overload.
  • Readiness → weighted composite, β-blocker-reweighted when propranolol taken.

## Timing awareness
If `training_load.last_session_date` is today, do NOT just say "Rest" — state what was
done, frame today as recovery, and prescribe the NEXT session from /api/workout/context.
Only a true Rest day if ACWR/gates warrant an off day beyond the session already logged.

## Write ONE deep report (sections in order)
- **Readiness** — recovery/sleep/HRV/RHR/resp-rate/load, what each signal *means* today.
- **Metrics & progression** — interpret the stats/summary analytics (ACWR trend, RHR vs
  baseline, recovery slope, sleep avg/consistency/debt). The analytical depth.
- **Patterns** — noteworthy items from /insights + correlations (omit if none).
- **Training call + next session** — call (Push/Train/Maintain/Easy/Rest) + the session
  from workout/context (timing-aware), respecting gates; goal = 5.0 pickleball while
  KEEPING strength + size (concurrent-training lens, not generic recomp). Cite vault notes.
- **Health story** — knowledgeable-friend narrative tying it together.
- **Body composition** — waist:shoulder / waist:hip + critique verdict vs lean-out-keep-size.
  No change claims the gated trend doesn't support; no body-fat %.

Write rich markdown: `##` subheads, **bold** key numbers, bullet lists. °F and lbs.
Direct and analytical, not flattering.

## Return — POST to http://127.0.0.1:8000/api/daily/report
{"training_call": "<Push|Train|Maintain|Easy|Rest>",
 "readiness_headline": "<one line>",
 "sections": [{"title": "Readiness", "body_md": "..."},
              {"title": "Metrics & progression", "body_md": "..."},
              {"title": "Patterns", "body_md": "..."},
              {"title": "Training call + next session", "body_md": "..."},
              {"title": "Health story", "body_md": "..."},
              {"title": "Body composition", "body_md": "..."}],
 "model": "claude"}
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
    model: str = "claude"


@router.post("/daily/report")
async def submit_daily_report(body: DailyReportSubmission) -> dict:
    """Persist a Claude-generated unified daily report (one row per day)."""
    if body.training_call and body.training_call not in _VALID_CALLS:
        raise HTTPException(422, f"training_call must be one of {sorted(_VALID_CALLS)}")
    sections_json = json.dumps([s.model_dump() for s in body.sections])
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO ai_daily_report
                (report_date, generated_at, model, training_call, readiness_headline, sections)
            VALUES (today(), now(), $model, $call, $headline, $sections)
            ON CONFLICT (report_date) DO UPDATE SET
                generated_at = excluded.generated_at,
                model = excluded.model,
                training_call = excluded.training_call,
                readiness_headline = excluded.readiness_headline,
                sections = excluded.sections
            """,
            {
                "model": body.model,
                "call": body.training_call,
                "headline": body.readiness_headline,
                "sections": sections_json,
            },
        )
    log.info("daily report stored — call=%s sections=%d", body.training_call, len(body.sections))
    return {"status": "ok"}


@router.get("/daily/report")
async def latest_daily_report() -> dict:
    """Return the most recent unified daily report."""
    row = get_read_conn().execute(
        "SELECT report_date, generated_at, model, training_call, readiness_headline, sections "
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
        }
    }
