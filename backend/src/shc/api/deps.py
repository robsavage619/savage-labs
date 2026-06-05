from __future__ import annotations

"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from shc.config import settings

_key_header = APIKeyHeader(name="X-SHC-Key", auto_error=False)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_admin_key(
    request: Request,
    key: Annotated[str | None, Depends(_key_header)],
) -> None:
    """Reject mutating requests that don't carry the configured admin key.

    Trusts loopback callers (the local CLI workout skill, the local browser
    frontend) without a key — this is a single-user local app and the TCP peer
    address is set by uvicorn from the real connection, not a spoofable header.
    The key gate still applies to every non-loopback caller, so the
    internet/Tailscale-facing surface remains protected. (The Apple Health
    webhook has its own independent key check in routers/apple.py and is
    unaffected by this.)

    Also skips the check when no key is configured (first-run, no .env).
    """
    client = request.client
    if client is not None and client.host in _LOOPBACK_HOSTS:
        return  # local CLI / local browser — trusted peer

    effective = settings.effective_admin_key
    if not effective:
        return  # no key configured — open (local dev only)
    if key != effective:
        raise HTTPException(status_code=401, detail="invalid key")
