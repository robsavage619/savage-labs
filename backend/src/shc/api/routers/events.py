from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["events"])


class EventIn(BaseModel):
    day: date
    label: str = Field(min_length=1, max_length=60)


@router.get("/events")
def list_events() -> list[dict[str, Any]]:
    """Every marker, newest first."""
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT id, day, label FROM events ORDER BY day DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [{"id": i, "day": d.isoformat(), "label": label} for i, d, label in rows]


@router.post("/events", dependencies=[Depends(require_admin_key)])
async def add_event(body: EventIn) -> dict[str, Any]:
    async with write_ctx() as conn:
        row = conn.execute(
            "INSERT INTO events (day, label) VALUES (?, ?) RETURNING id",
            [body.day, body.label.strip()],
        ).fetchone()
    assert row is not None
    return {"id": row[0], "day": body.day.isoformat(), "label": body.label.strip()}


@router.delete("/events/{event_id}", dependencies=[Depends(require_admin_key)])
async def delete_event(event_id: int) -> dict[str, int]:
    async with write_ctx() as conn:
        row = conn.execute("DELETE FROM events WHERE id = ? RETURNING id", [event_id]).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such event")
    return {"deleted": event_id}
