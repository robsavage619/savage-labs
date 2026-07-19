from __future__ import annotations

"""n-of-1 self-experiment API — register a study, log daily adherence, score it.

Thin HTTP surface over :mod:`shc.selflab`. Reads are open; mutations are
admin-key gated like the rest of the platform. The analysis itself is entirely
in ``selflab`` (deterministic, tested) — this layer only marshals I/O.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shc import selflab
from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["experiments"])


class PreregisterIn(BaseModel):
    slug: str
    hypothesis: str
    manipulated: str
    condition_a: str
    condition_b: str
    outcome_metric: str
    # Required, not defaulted: min_effect=0 makes REFUTED structurally
    # impossible and CONFIRMS on a trivially small effect — see
    # selflab.preregister's docstring. The caller must state the smallest
    # effect worth acting on before data collection starts.
    min_effect: float = Field(gt=0)
    outcome_direction: str = "higher_better"
    min_per_arm: int = 6
    washout_hours: int = 0
    notes: str | None = None


class LogDayIn(BaseModel):
    day: date | None = None  # defaults to today
    adhered: bool = True
    note: str | None = None


@router.get("/experiments")
async def list_experiments() -> list[dict]:
    """Every study with its config, latest result, prior, and adherence counts."""
    conn = get_read_conn()
    try:
        return selflab.overview(conn)
    finally:
        conn.close()


@router.get("/experiments/suggestions")
async def experiment_suggestions() -> list[dict]:
    """Candidate n-of-1 study specs derived from unresolved lab findings.

    Returns specs for controllable-behavior questions that are still
    inconclusive/insufficient and don't have a registered study yet.
    """
    conn = get_read_conn()
    try:
        return selflab.suggest_experiments(conn)
    finally:
        conn.close()


@router.get("/experiments/priors")
async def experiment_priors() -> list[dict]:
    """Confirmed, causal personal priors the engine may act on."""
    conn = get_read_conn()
    try:
        return selflab.active_priors(conn)
    finally:
        conn.close()


@router.post("/experiments", dependencies=[Depends(require_admin_key)])
async def preregister_experiment(body: PreregisterIn) -> dict:
    async with write_ctx() as conn:
        existing = conn.execute(
            "SELECT 1 FROM experiments WHERE slug = ?", [body.slug]
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"experiment {body.slug!r} already exists")
        exp_id = selflab.preregister(
            conn,
            slug=body.slug,
            hypothesis=body.hypothesis,
            manipulated=body.manipulated,
            condition_a=body.condition_a,
            condition_b=body.condition_b,
            outcome_metric=body.outcome_metric,
            outcome_direction=body.outcome_direction,
            min_per_arm=body.min_per_arm,
            min_effect=body.min_effect,
            washout_hours=body.washout_hours,
            notes=body.notes,
        )
    return {"id": exp_id, "slug": body.slug}


@router.post("/experiments/{slug}/log", dependencies=[Depends(require_admin_key)])
async def log_experiment_day(slug: str, body: LogDayIn) -> dict:
    """Record adherence for a day; the assigned arm is computed, not chosen."""
    day = body.day or date.today()
    async with write_ctx() as conn:
        exp = selflab.load(conn, slug)
        if exp is None:
            raise HTTPException(status_code=404, detail=f"no experiment {slug!r}")
        arm = selflab.log_day(conn, exp.id, day, adhered=body.adhered, note=body.note)
    return {"slug": slug, "day": day.isoformat(), "assigned_arm": arm, "adhered": body.adhered}


@router.post("/experiments/{slug}/score", dependencies=[Depends(require_admin_key)])
async def score_experiment(slug: str) -> dict:
    """Pull outcomes from the training stream, then score → verdict + effect + CI.

    Scores this ONE experiment in isolation — no Benjamini–Hochberg correction
    against other studies. Prefer POST /experiments/score-all when scoring more
    than one experiment (e.g. a routine portfolio-wide re-score); calling this
    endpoint repeatedly across several experiments skips the multiplicity
    control that path applies.
    """
    async with write_ctx() as conn:
        exp = selflab.load(conn, slug)
        if exp is None:
            raise HTTPException(status_code=404, detail=f"no experiment {slug!r}")
        selflab.refresh_outcomes(conn, exp.id)
        return selflab.score(conn, exp.id)


@router.post("/experiments/score-all", dependencies=[Depends(require_admin_key)])
async def score_all_experiments() -> list[dict]:
    """Refresh outcomes and score every active experiment together, with
    Benjamini–Hochberg correction across the batch's p-values — the
    multiplicity-controlled way to re-score the whole portfolio."""
    async with write_ctx() as conn:
        active_ids = [
            row[0]
            for row in conn.execute("SELECT id FROM experiments WHERE status = 'active'").fetchall()
        ]
        for exp_id in active_ids:
            selflab.refresh_outcomes(conn, exp_id)
        return selflab.score_all(conn)
