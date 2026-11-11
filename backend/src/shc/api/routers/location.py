from __future__ import annotations

import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from shc import places
from shc.api.deps import require_admin_key
from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx

log = logging.getLogger(__name__)

router = APIRouter(tags=["location"])

_basic = HTTPBasic(auto_error=False)


def _require_webhook_key(creds: Annotated[HTTPBasicCredentials | None, Depends(_basic)]) -> None:
    """OwnTracks sends HTTP Basic; the password is the webhook key, the username is ignored."""
    if not settings.apple_webhook_key:
        raise HTTPException(status_code=503, detail="apple_webhook_key not configured")
    if creds is None or not secrets.compare_digest(
        creds.password.encode(), settings.apple_webhook_key.encode()
    ):
        raise HTTPException(
            status_code=401, detail="invalid key", headers={"WWW-Authenticate": "Basic"}
        )


@router.post("/location/owntracks", dependencies=[Depends(_require_webhook_key)])
async def owntracks(request: Request) -> list[Any]:
    """OwnTracks HTTP endpoint. Replies `[]`, the empty command list OwnTracks expects."""
    try:
        msg = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="body is not JSON") from exc
    if not isinstance(msg, dict):
        return []
    async with write_ctx() as conn:
        if places.ingest_owntracks(conn, msg):
            new = places.update_stays(conn)
            if new:
                log.info("location: %d new stays", new)
    return []


@router.get("/places")
def get_places() -> dict[str, Any]:
    """Discovered places, their pattern, and their stress and next-morning effects."""
    conn = get_read_conn()
    try:
        return places.summary(conn)
    finally:
        conn.close()


class PlaceName(BaseModel):
    name: str | None = Field(default=None, max_length=60)


@router.patch("/places/{place_id}", dependencies=[Depends(require_admin_key)])
async def name_place(place_id: int, body: PlaceName) -> dict[str, Any]:
    """Name a place, or clear its name with null."""
    name = body.name.strip() if body.name else None
    async with write_ctx() as conn:
        row = conn.execute(
            "UPDATE places SET name = ? WHERE id = ? RETURNING id", [name or None, place_id]
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such place")
    return {"id": place_id, "name": name or None}
