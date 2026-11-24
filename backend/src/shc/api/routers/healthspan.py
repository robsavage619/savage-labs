from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from shc.db import schema
from shc.health_markers import evaluate

router = APIRouter(tags=["healthspan"])


@router.get("/healthspan")
def get_healthspan() -> list[dict[str, Any]]:
    """Every health marker with its latest value, trend, target and status (read-only)."""
    conn = schema.get_read_conn()
    try:
        return evaluate(conn)
    finally:
        conn.close()
