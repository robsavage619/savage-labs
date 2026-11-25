from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from shc import rob_model
from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["model"])


# Plain `def`: FastAPI runs it in the threadpool, so DuckDB work cannot block the loop.
@router.get("/model")
def model_parameters() -> dict[str, Any]:
    """What the lab knows about Rob, by domain. Read-only."""
    conn = get_read_conn()
    try:
        domains = rob_model.read_all(conn)
    finally:
        conn.close()
    return {"count": sum(len(v) for v in domains.values()), "domains": domains}


@router.get("/model/prediction")
def model_prediction(target: str = "recovery_score") -> dict[str, Any]:
    """Rolling-origin ridge backtest of one target, with ablation. Read-only; feeds nothing."""
    from shc import prediction, research

    conn = get_read_conn()
    try:
        return prediction.backtest(conn, target)
    except research.SpecError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    finally:
        conn.close()


@router.post("/model/refresh", dependencies=[Depends(require_admin_key)])
async def model_refresh() -> dict[str, Any]:
    """Re-read the engine's fits into the registry."""
    async with write_ctx() as conn:
        return rob_model.refresh(conn)
