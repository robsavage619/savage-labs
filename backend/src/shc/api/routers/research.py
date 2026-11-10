from __future__ import annotations

"""The research team's API: the data dictionary, beliefs, pre-registered
hypotheses, runs, and the append-only notebook. Agents write through the
admin-keyed routes; the Lab page reads the rest."""

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


class HypothesisIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$")
    question: str
    spec: dict[str, Any]
    belief_id: str | None = None
    author: str = "analyst"
    rationale: str = ""


class NoteIn(BaseModel):
    author: str
    kind: str = Field(pattern=r"^(proposal|review|note|rejection)$")
    title: str
    body: str = ""
    ref: str | None = None


def _read(fn, *args):
    conn = get_read_conn()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


@router.get("/research/features")
async def features() -> list[dict]:
    """What the team can study: every feature, its coverage, and whether it's gone quiet."""
    return _read(research.dictionary)


@router.get("/research/beliefs")
async def list_beliefs() -> list[dict]:
    return _read(research.beliefs)


@router.get("/research/hypotheses")
async def list_hypotheses() -> list[dict]:
    return _read(research.hypotheses)


@router.get("/research/notebook")
async def list_notebook(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
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
        return {"id": research.note(conn, body.author, body.kind, body.title, body.body, body.ref)}


@router.get("/research/forecast")
async def forecast() -> dict:
    """The lab's skill at predicting next-morning HRV, backtest and live."""
    return _read(research.forecast_view)


@router.post("/research/backtest", dependencies=[Depends(require_admin_key)])
async def backtest() -> dict:
    async with write_ctx() as conn:
        bt = research.backtest(conn)
        research.store_backtest(conn, bt)
        research.forecast_today(conn)
    return {k: v for k, v in bt.items() if k != "series"}


class ReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    reasons: str = Field(min_length=10)
    author: str = "methodologist"


class ScoreIn(BaseModel):
    spec: dict[str, Any]
    belief_id: str | None = None


@router.get("/research/brief")
async def research_brief() -> dict:
    """The analyst's starting point: beliefs, questions, notebook, forecast misses, data."""
    return _read(research.brief)


@router.get("/research/review-queue")
async def review_queue() -> list[dict]:
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
            return research.review(conn, slug, body.decision, body.reasons, body.author)
        except research.SpecError as exc:
            raise HTTPException(409, str(exc)) from exc
