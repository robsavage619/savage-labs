from __future__ import annotations

"""The research team's API: the data dictionary, beliefs, pre-registered
hypotheses, runs, and the append-only notebook. Agents write through the
admin-keyed routes; the Lab page reads the rest."""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from shc import research
from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["research"])


class BeliefIn(BaseModel):
    claim: str
    outcome: str
    prior_mean: float
    prior_sd: float = Field(gt=0)
    prior_source: str = Field(min_length=3)
    decision: str | None = None
    author: str = "analyst"
    # The effect's unit; derived from the outcome feature when omitted.
    unit: str | None = None


class HypothesisIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    question: str
    spec: dict[str, Any]
    belief_id: str | None = None
    author: str = "analyst"
    rationale: str = ""
    follows: str = ""
    what_changed: str = ""


class NoteIn(BaseModel):
    author: str
    kind: str = Field(pattern=r"^(proposal|review|note|rejection)$")
    title: str
    body: str = ""
    ref: str | None = None


# Read routes are plain `def` so FastAPI runs them in its threadpool: as `async def`
# they did synchronous DuckDB work on the event loop, and one slow /features call
# (about 9 s) held every other Lab request behind it.
def _read(fn, *args):
    conn = get_read_conn()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


# ponytail: one in-process copy for _FEATURES_TTL_S, because building the dictionary
# runs every feature's series (about 9.5 s on the host); a newly approved custom
# measure appears within that window. Cache inside research.dictionary if brief()
# or review_queue() ever need it faster too.
_FEATURES_TTL_S = 600.0
_features_cache: tuple[float, list[dict]] | None = None


@router.get("/research/features")
def features() -> list[dict]:
    """What the team can study: every feature, its coverage, and whether it's gone quiet."""
    global _features_cache
    now = time.monotonic()
    if _features_cache is not None and now - _features_cache[0] < _FEATURES_TTL_S:
        return _features_cache[1]
    out = _read(research.dictionary)
    _features_cache = (now, out)
    return out


@router.get("/research/beliefs")
def list_beliefs() -> list[dict]:
    return _read(research.beliefs)


@router.get("/research/hypotheses")
def list_hypotheses() -> list[dict]:
    return _read(research.hypotheses)


@router.get("/research/notebook")
def list_notebook(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return _read(research.notebook, limit)


@router.post("/research/beliefs", dependencies=[Depends(require_admin_key)])
async def add_belief(body: BeliefIn) -> dict:
    async with write_ctx() as conn:
        try:
            bid = research.add_belief(
                conn,
                body.claim,
                body.outcome,
                body.prior_mean,
                body.prior_sd,
                body.prior_source,
                body.decision,
                body.author,
                body.unit,
            )
        except research.SpecError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"id": bid}


@router.post("/research/hypotheses", dependencies=[Depends(require_admin_key)])
async def register(body: HypothesisIn) -> dict:
    """Pre-register a spec. Power decides whether it is `registered` or `underpowered`."""
    async with write_ctx() as conn:
        try:
            return research.register(
                conn,
                body.slug,
                body.question,
                body.spec,
                body.belief_id,
                body.author,
                body.rationale,
                body.follows,
                body.what_changed,
            )
        except research.SpecError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post("/research/hypotheses/{slug}/run", dependencies=[Depends(require_admin_key)])
async def run_one(slug: str) -> dict:
    async with write_ctx() as conn:
        try:
            return research.run(conn, slug)
        except research.SpecError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.post("/research/run-all", dependencies=[Depends(require_admin_key)])
async def run_all() -> list[dict]:
    async with write_ctx() as conn:
        return research.run_all(conn)


@router.post("/research/notebook", dependencies=[Depends(require_admin_key)])
async def add_note(body: NoteIn) -> dict:
    async with write_ctx() as conn:
        try:
            research.check_proposal(conn, body.title, body.body)
        except research.SpecError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": research.note(conn, body.author, body.kind, body.title, body.body, body.ref)}


_METRIC = Query(
    research.FORECAST_METRIC, description="Forecast target; next-morning HRV by default."
)


def _target(metric: str) -> str:
    try:
        return research.forecast_target(metric).metric
    except research.SpecError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/research/forecast")
def forecast(metric: str = _METRIC) -> dict:
    """The lab's skill at predicting a target (next-morning HRV by default), backtest and live."""
    m = _target(metric)
    return _read(lambda c: research.forecast_view(c, metric=m))


@router.post("/research/backtest", dependencies=[Depends(require_admin_key)])
async def backtest(metric: str | None = None) -> dict:
    """Backtest and log today's bet for one target, or every target when none is named.

    The response is the named target's summary (HRV when none is named), with
    every target's summary under `targets`.
    """
    metrics = [_target(metric)] if metric else list(research.FORECAST_TARGETS)
    out: dict[str, dict] = {}
    async with write_ctx() as conn:
        for m in metrics:
            bt = research.backtest(conn, metric=m)
            research.store_backtest(conn, bt)
            research.forecast_today(conn, metric=m)
            out[m] = {k: v for k, v in bt.items() if k != "series"}
    return out[metrics[0]] | {"targets": out}


class ReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject|revise)$")
    reasons: str = Field(min_length=10)
    author: str = "methodologist"
    # With `revise`: the design the reviewer would accept, registered as active.
    revised_spec: dict[str, Any] | None = None
    revised_question: str | None = None


class ScoreIn(BaseModel):
    spec: dict[str, Any]
    belief_id: str | None = None


@router.get("/research/brief")
def research_brief() -> dict:
    """The analyst's starting point: beliefs, questions, notebook, forecast misses, data."""
    return _read(research.brief)


@router.get("/research/review-queue")
def review_queue() -> list[dict]:
    """Proposed questions for the methodologist, without the analyst's reasoning."""
    return _read(research.review_queue)


@router.post("/research/score")
async def score_candidate(body: ScoreIn) -> dict:
    """Validate a draft spec and return its power and value without registering it."""
    conn = get_read_conn()
    try:
        research.validate_spec(conn, body.spec)
        est = research.estimate(conn, body.spec)
        pw = est.get("power")
        return {
            "n_a": est["n_a"],
            "n_b": est["n_b"],
            "power": pw,
            "value": research.value_score(conn, body.spec, body.belief_id, power=pw),
        }
    except research.SpecError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()


@router.post("/research/hypotheses/{slug}/review", dependencies=[Depends(require_admin_key)])
async def review(slug: str, body: ReviewIn) -> dict:
    async with write_ctx() as conn:
        try:
            return research.review(
                conn,
                slug,
                body.decision,
                body.reasons,
                body.author,
                body.revised_spec,
                body.revised_question,
            )
        except research.SpecError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.get("/research/forecast/preview")
def forecast_preview(metric: str = _METRIC) -> dict:
    """The next bet on a target and the beliefs behind it (computed, not logged)."""
    m = _target(metric)
    return _read(lambda c: research.forecast_preview(c, metric=m))


@router.get("/research/misses")
def misses(metric: str = Query(research.FORECAST_METRIC)) -> dict:
    """Where the latest backtest of a target went most wrong: the analysts' agenda."""
    conn = get_read_conn()
    try:
        return research.misses(conn, metric)
    except research.SpecError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()


class RetireIn(BaseModel):
    reason: str = Field(min_length=10)
    author: str = "methodologist"


@router.post("/research/hypotheses/{slug}/retire", dependencies=[Depends(require_admin_key)])
async def retire(slug: str, body: RetireIn) -> dict:
    """Stop running an active question; its results and notebook trail stay."""
    async with write_ctx() as conn:
        try:
            return research.retire(conn, slug, body.reason, body.author)
        except research.SpecError as exc:
            raise HTTPException(409, str(exc)) from exc
