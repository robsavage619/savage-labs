from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from shc.ingest.whoop import exchange_code, get_auth_url, sync_all
from shc.ingest.apple_xml import ingest_export

_APPLE_HEALTH_XML = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Health Data/Fitness Data/export.xml"

router = APIRouter(tags=["auth"])


@router.get("/whoop/login")
async def whoop_login() -> RedirectResponse:
    return RedirectResponse(get_auth_url())


@router.get("/whoop/callback")
async def whoop_callback(code: str, state: str) -> dict:
    try:
        await exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Kick off an immediate sync after auth
    await sync_all()
    return {"status": "authorized"}


@router.post("/whoop/sync")
async def whoop_sync() -> dict:
    """Manually trigger a WHOOP sync."""
    try:
        await sync_all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/apple/ingest")
async def apple_ingest() -> dict:
    """Stream Apple Health export.xml into the measurements table."""
    if not _APPLE_HEALTH_XML.exists():
        raise HTTPException(status_code=404, detail=f"export.xml not found at {_APPLE_HEALTH_XML}")
    try:
        counts = await ingest_export(_APPLE_HEALTH_XML)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "counts": counts}
