"""The research team's autonomy routes: specialist agendas, custom
measurements, free exploration, and exploration notes. Writes are admin-keyed;
nothing here touches beliefs or the training engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shc import research_team
from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["research-team"])


class AgendaIn(BaseModel):
    interests: str = ""
    open_leads: list[dict[str, Any]] = Field(default_factory=list)
    hunches: str = ""
    next_steps: str = ""


class CustomFeatureIn(BaseModel):
    slug: str
    owner: str
    description: str
    unit: str
    timing: str
    sql: str


class CustomReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    reason: str = Field(min_length=10)
    author: str = "methodologist"


class QueryIn(BaseModel):
    sql: str
    limit: int = Field(research_team.EXPLORE_ROW_CAP, ge=1, le=research_team.EXPLORE_ROW_CAP)


class ExplorationIn(BaseModel):
    author: str
    title: str
    looked_at: str
    numbers: str
    lead: str = ""
    lead_effect: str = Field("neither", pattern=r"^(opens|closes|neither)$")


@router.get("/research/team")
def team() -> list[dict]:
    """Each specialist with their agenda and last notebook activity."""
    conn = get_read_conn()
    try:
        return research_team.team(conn)
    finally:
        conn.close()


@router.put("/research/team/{researcher}/agenda", dependencies=[Depends(require_admin_key)])
async def put_agenda(researcher: str, body: AgendaIn) -> dict:
    """Replace a specialist's agenda; the notebook records what changed."""
    if researcher not in research_team.RESEARCHERS:
        raise HTTPException(404, f"unknown researcher {researcher!r}")
    async with write_ctx() as conn:
        try:
            return research_team.set_agenda(conn, researcher, body.model_dump())
        except research_team.TeamError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.get("/research/custom-features")
def custom_features() -> list[dict]:
    """Every proposed, approved and rejected custom measurement, with its SQL."""
    conn = get_read_conn()
    try:
        return research_team.list_custom(conn)
    finally:
        conn.close()


@router.post("/research/custom-features", dependencies=[Depends(require_admin_key)])
async def propose_custom(body: CustomFeatureIn) -> dict:
    """Propose a measurement; it is run and shape-checked before it is stored."""
    async with write_ctx() as conn:
        try:
            return await run_in_threadpool(
                research_team.propose_custom,
                conn,
                body.slug,
                body.owner,
                body.description,
                body.unit,
                body.timing,
                body.sql,
            )
        except research_team.TeamError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post("/research/custom-features/{name}/review", dependencies=[Depends(require_admin_key)])
async def review_custom(name: str, body: CustomReviewIn) -> dict:
    """The methodologist approves or rejects a proposed measurement."""
    async with write_ctx() as conn:
        try:
            return research_team.review_custom(conn, name, body.decision, body.reason, body.author)
        except research_team.TeamError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post("/research/query", dependencies=[Depends(require_admin_key)])
def query(body: QueryIn) -> dict:
    """Guarded read-only SQL for free exploration, capped at 2000 rows."""
    conn = get_read_conn()
    try:
        return research_team.run_query(conn, body.sql, body.limit)
    except research_team.TeamError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        conn.close()


@router.post("/research/explorations", dependencies=[Depends(require_admin_key)])
async def add_exploration(body: ExplorationIn) -> dict:
    """Record an exploration in the notebook. Never touches beliefs or the engine."""
    async with write_ctx() as conn:
        try:
            nid = research_team.record_exploration(
                conn,
                body.author,
                body.title,
                body.looked_at,
                body.numbers,
                body.lead,
                body.lead_effect,
            )
        except research_team.TeamError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"id": nid}
