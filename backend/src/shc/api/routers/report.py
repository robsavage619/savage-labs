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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shc.api.deps import require_admin_key
from shc.api.routers.training import dupr_rating
from shc.db.schema import get_read_conn, write_ctx
from shc.ingest import dupr, hevy, whoop
from shc.metrics import compute_daily_state

router = APIRouter(tags=["daily-report"])
log = logging.getLogger(__name__)

_VALID_CALLS = {"Push", "Train", "Maintain", "Easy", "Rest"}


def failed_endpoints(detail: object) -> list[str]:
    """Endpoint names a source reported as failed via a negative record count.

    `whoop.sync_all` isolates per-endpoint failures and marks them `-1` rather
    than raising, so a source can hand back a detail map that looks like a
    success. Any negative count means that endpoint wrote nothing — the source
    is a partial failure, never `ok`.
    """
    if not isinstance(detail, dict):
        return []
    return sorted(k for k, v in detail.items() if isinstance(v, int | float) and v < 0)


@router.post("/sync/all", dependencies=[Depends(require_admin_key)])
async def sync_all() -> dict:
    """Force a fresh pull from every connected source before reporting.

    Runs the same WHOOP / Hevy / DUPR syncs the scheduler does, on demand. Each
    source is isolated — one failing (auth, network) never blocks the others; the
    per-source outcome is returned so failures are visible, not silent. A source
    that completes with some endpoints failed reports `ok: false` plus
    `partial: true` and `failed_endpoints`. Apple Health ingests automatically
    via the file watcher, so it isn't pulled here.
    """
    sources = (("whoop", whoop.sync_all), ("hevy", hevy.sync_workouts), ("dupr", dupr.sync_rating))
    results: dict[str, dict] = {}
    partial: list[str] = []
    for name, fn in sources:
        try:
            detail = await fn()
        except Exception as exc:  # isolate per source — surface, don't abort
            log.warning("sync %s failed: %s", name, exc)
            results[name] = {"ok": False, "error": str(exc)}
            continue
        failed = failed_endpoints(detail)
        if failed:
            log.error("sync %s partial — endpoints failed: %s", name, failed)
            partial.append(name)
            results[name] = {
                "ok": False,
                "partial": True,
                "failed_endpoints": failed,
                "error": f"{name} endpoints failed: {', '.join(failed)}",
                "detail": detail,
            }
        else:
            results[name] = {"ok": True, "detail": detail}

    # Freshness is read back out of the DB after the syncs, so it describes what
    # actually persisted rather than what was attempted.
    freshness = compute_daily_state(get_read_conn()).get("freshness", {})
    for name in partial:
        endpoints = ", ".join(results[name]["failed_endpoints"])
        freshness.setdefault("gaps", []).append(
            f"{name} sync PARTIAL — endpoints failed: {endpoints} (data below may be incomplete)"
        )
    return {"results": results, "freshness": freshness}


_PROMPT = """\
Generate Rob's COMPLETE daily report in one pass. This is the SINGLE report and must
carry the FULL depth and research grounding — it replaces the old briefing,
health-story, workout, and analytics dashboard. Be thorough and analytical, never thin.

## Sync first, then pull ALL of these
1. POST http://127.0.0.1:8000/api/sync/all — refresh WHOOP / Hevy / DUPR. Note any
   source returning `ok: false` — including `partial: true` (some endpoints failed;
   see `failed_endpoints`). A partial sync means the numbers below may be stale:
   re-run the sync before trusting them, and say so if they stay partial.
2. GET http://127.0.0.1:8000/api/daily/brief — DailyState (full metric set below),
   recent training, AND the curated vault research notes. Single source of numbers.
3. GET http://127.0.0.1:8000/api/workout/context — TIMING-AWARE workout plan (if Rob
   trained today it auto-plans the NEXT session). Use for the training section.
4. GET http://127.0.0.1:8000/api/stats/summary — ACWR, RHR elevation, recovery-trend
   slope, sleep avg/consistency/debt analytics.
5. GET http://127.0.0.1:8000/api/insights AND /api/insights/correlations — detected
   patterns.
6. GET http://127.0.0.1:8000/api/progress-photos/critique — physique verdict (null → say so).
7. GET http://127.0.0.1:8000/api/clinical/risk — cardiometabolic strip, overdue lab gaps,
   medication advisories, and the `hepatic` FIB-4 fibrosis index. Health-story material.
8. GET http://127.0.0.1:8000/api/experiments — pre-registered n-of-1 studies. A CONFIRMED
   study is Rob's OWN evidence and outranks a general vault note where the two disagree;
   say so explicitly when one bears on today.
9. GET http://127.0.0.1:8000/api/pickleball/events — per-tournament readiness shape (7 days
   before → 3 after, joined to W-L and net DUPR movement). Use it when an event is recent
   or upcoming, and honor its `sample_warning` rather than over-reading a small n.

## Use the FULL metric set — do not cherry-pick
Recovery: HRV + **hrv_sigma** (σ vs 28d baseline), RHR + elevation%, skin-temp delta
(already °F), **respiratory_rate_delta**, last night's SpO2 AND the 14-night burden
(**spo2_nights_14d / spo2_lt95_nights_14d**), WHOOP autonomic stress (**stress_level**,
**stress_high_rate_7d**, with **stress_days_7d** as the sample guard), calibration flag.
Sleep: deep%/**REM%**/**efficiency%**/consistency/performance, the **sleep-need breakdown**
(base/debt/strain/nap), debt_7d, midpoint + midpoint variability, and
**midpoint_vs_optimal_h** — how far the midpoint sits from WHOOP's recommended window, a
different question from how much it moves. Training load: pooled ACWR (+ acute_load_7d /
chronic_load_21d) AND the modality split **resistance_acwr / conditioning_acwr**,
**day_strain_yesterday / day_strain_7d_avg**, days-since legs/push/pull/**pickleball**,
per-muscle **muscle_recovery** (two clocks, don't confuse them: `days_since_dose` is the rest gate's input — days since a ≥4-set dose — while `days_since_any_primary_set` is when the muscle was last touched at all; quote the second one for "when did he last train X"), push:pull balance, **pickleball_min_7d/28d**, **cardio zone
minutes (z0–z5)** read against **hr_zone_bounds** (WHOOP's real boundaries — Z5 starts at
~93% of max, not the textbook 90%), **cardio_aerobic_base_min_7d**, max HR. Plus readiness
(weighted, β-blocker), check-in subjectives, gates (including **forbid_muscles** and
**e1rm_regression_cause**), body_composition, freshness.

Two traps in that set. `cardio_high_intensity_min_7d` reads roughly 10× high — cross-check
it against z3+z4+z5 and cite the zone sum, never the field. And `cardio_z2_min_7d` is
WHOOP's Z2 band alone, while the ~180 min/wk aerobic-base dose spans WHOOP Z2 **and** Z3 —
answer "is he getting enough Z2?" from `cardio_aerobic_base_min_7d`, or you undercount by
about 40%.

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
  • ACWR → true **Gabbett** acute/chronic, but the POOLED value is DISPLAY-ONLY: it is
    blind to which system is loaded, so a pickleball weekend inflates it and rest-gates
    lifting that isn't overloaded. Read **resistance_acwr** for lifting and
    **conditioning_acwr** for court/cardio, apply the thresholds per modality
    (>1.5 = cap MODERATE; >1.8 = cap LOW; >2.0 = rest), and name which one drove the call.
  • SpO2 → one night is noise. Interpret the 14-night burden; <95% is a screening signal,
    and only sustained <92% is an intensity question.
  • Chronic stress → **surfaced, never capping**. Report it as autonomic context, only
    when `stress_days_7d` is enough days to mean anything, and never let it move the
    training call on its own.
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
narrative only.

**The plan schema is the `## OUTPUT SCHEMA` TypeScript block inside
`/api/workout/context`. Build against THAT block verbatim — it is the copy the validator
enforces. Do not work from memory or from an older example.** Field names are strict
(`label` not `name`, `cooldown` a plain string). These are the fields most often dropped,
each of which either rejects the plan outright or renders the card empty:
- `recommendation.target_rpe` — **required** on every non-rest, non-deload plan. Omitting
  it is a hard **422**, not a warning.
- `readiness_summary`; `recommendation.summary` (ONE plain-English sentence, the only prose
  on the dashboard — obey the schema's VOICE rules, no jargon, ≤25 words);
  `recommendation.rationale` (the technical audit trail, and a DIFFERENT sentence from
  `summary`); `recommendation.estimated_duration_min`; and `warmup[]`. All four are
  rendered — skip one and that part of the card goes blank.
- `rest_seconds` on every exercise, no exceptions. `clinical_notes` is a **list** of
  strings, not a string.

Hard constraints from the same context: `recommendation.intensity` must not exceed the
gate's max intensity; every loaded exercise must stay under the e1RM load ceiling; respect
BOTH `forbid_muscle_groups` and the per-muscle `forbid_muscles` (a plan honoring only the
coarse list still 409s); every `vault_insights` filename must be a real catalog note.

Before writing the first exercise, run the pre-POST checklist in CLAUDE.md — the
ceiling-vs-last-weight gap test, and synergist credit counted at **1.0/set** rather than
the 0.5 the context text prints. These rejections recur precisely when that checklist gets
read after a 409 instead of before the first exercise.

## Write ONE deep report (sections in order)
- **Readiness** — recovery/sleep/HRV/RHR/resp-rate/load, what each signal *means* today.
- **Metrics & progression** — interpret the stats/summary analytics (ACWR trend, RHR vs
  baseline, recovery slope, sleep avg/consistency/debt). The analytical depth.
- **Patterns** — noteworthy items from /insights + correlations (omit if none).
- **Training call + next session** — call (Push/Train/Maintain/Easy/Rest) + the session
  from workout/context (timing-aware), respecting gates. Rob is 40 and training to peak
  athletic form — not maintaining, PEAKING. Goal: __DUPR_GOAL__, concurrent strength +
  size (not generic recomp). He refuses to let age set the ceiling; your job is to
  design sessions that honor that. Push hard when gates allow.
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


def _dupr_goal_clause() -> str:
    """Render the DUPR goal from the live synced rating, not a hardcoded absolute.

    A static "4.5 → 5.0" drifted years away from the real rating and made every
    narrative claim a goal Rob is nowhere near. Reuses the training router's
    target so the report prompt and the goal scorecard can never disagree.
    """
    try:
        rating = dupr_rating()
        current = (rating.get("current") or {}).get("doubles")
        target = rating.get("target_doubles")
    except Exception as exc:  # a goal line must never break the prompt
        log.warning("dupr goal clause failed: %s", exc)
        return "raise DUPR doubles pickleball rating"
    if current is None or target is None:
        return "raise DUPR doubles pickleball rating"
    return f"{current:.3f} → {target:.2f} DUPR doubles pickleball"


@router.get("/daily/report/prompt")
async def daily_report_prompt() -> dict:
    """Return the single prompt that generates the whole daily report."""
    return {"prompt": _PROMPT.replace("__DUPR_GOAL__", _dupr_goal_clause())}


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


@router.post("/daily/report", dependencies=[Depends(require_admin_key)])
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
        body.mode,
        body.training_call,
        len(body.sections),
        len(body.sources),
    )
    return {"status": "ok"}


@router.get("/daily/report")
async def latest_daily_report() -> dict:
    """Return the most recent unified daily report."""
    row = (
        get_read_conn()
        .execute(
            "SELECT report_date, generated_at, model, training_call, readiness_headline, "
            "sections, sources, mode "
            "FROM ai_daily_report ORDER BY report_date DESC LIMIT 1"
        )
        .fetchone()
    )
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
