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
    key = settings.apple_webhook_key
    if creds is not None and secrets.compare_digest(creds.password.encode(), key.encode()):
        return
    if creds is None:
        reason = "no credentials sent"
    else:
        trimmed = creds.password.strip().strip('"').strip()
        reason = (
            f"password mismatch (sent {len(creds.password)} chars, key is {len(key)}"
            f"{'; matches once whitespace/quotes are trimmed' if trimmed == key else ''})"
        )
    log.warning("owntracks 401: %s", reason)
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
    # A reconnecting phone can flush its queue as one JSON array.
    msgs = [m for m in (msg if isinstance(msg, list) else [msg]) if isinstance(m, dict)]
    async with write_ctx() as conn:
        kept = sum(places.ingest_owntracks(conn, m) for m in msgs)
        new = places.update_stays(conn) if kept else 0
    log.info("owntracks: %d of %d messages kept, %d new stays", kept, len(msgs), new)
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
