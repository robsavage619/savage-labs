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
Generate Rob's COMPLETE daily report in one pass — this replaces the separate
briefing, health-story, workout, and body-composition runs.

## Sync first, then pull your inputs
1. POST http://127.0.0.1:8000/api/sync/all
   — force-refresh WHOOP / Hevy / DUPR so the report runs on current data. Note any
     source that comes back `ok: false` (mention it in Readiness if a key feed failed).
2. GET http://127.0.0.1:8000/api/daily/brief
   — DailyState (recovery, sleep, training load, readiness, AUTO-REG GATES,
     body_composition, freshness), top vault notes, and recent training. This is your
     single source of numbers — never recompute them.
3. GET http://127.0.0.1:8000/api/progress-photos/critique
   — latest physique critique: use its `verdict` and the body-composition takeaway.
     If `critique` is null, say body-composition tracking has no critique yet.

## Write ONE report with these sections (in order)
- **Readiness** — what the recovery/sleep/HRV/load numbers mean today.
- **Training call + today's workout** — the call (Push/Train/Maintain/Easy/Rest)
  and the actual session, RESPECTING the auto-reg gates in DailyState. Honor the
  goal: climb to 5.0 pickleball while KEEPING strength + size (concurrent-training
  lens, not generic recomp).
- **Health story** — the knowledgeable-friend narrative tying it together.
- **Body composition** — interpret waist:shoulder / waist:hip + the critique verdict
  against the lean-out-keep-size goal. Do NOT claim change the gated trend doesn't
  support; do NOT estimate body-fat %.

Use °F and lbs. Be direct, not flattering.

## Return — POST to http://127.0.0.1:8000/api/daily/report
{"training_call": "<Push|Train|Maintain|Easy|Rest>",
 "readiness_headline": "<one line>",
 "sections": [{"title": "Readiness", "body_md": "..."},
              {"title": "Training call + workout", "body_md": "..."},
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
