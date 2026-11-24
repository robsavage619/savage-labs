from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from shc import block_experiment
from shc.db.schema import get_read_conn

router = APIRouter(tags=["experiments"])


# Plain `def`: FastAPI runs it in the threadpool, so DuckDB work cannot block the loop.
@router.get("/experiments/block")
def block_experiment_score() -> dict[str, Any]:
    """Read-only score of the left-against-right biceps experiment."""
    conn = get_read_conn()
    try:
        return block_experiment.score(conn)
    finally:
        conn.close()
