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

    Trusts two callers without a key: a direct loopback peer (the local CLI, the
    scheduled sync, an SSH tunnel), and a request `tailscale serve` proxied for a
    logged-in tailnet user, recognised by the `Tailscale-User-Login` header that
    tailscaled sets and strips from incoming requests. Behind `serve`, uvicorn
    rewrites the client address from X-Forwarded-For, so those requests never look
    like loopback and the header is the only signal. A forwarded request without
    it (Funnel, a tagged device) needs the key. (The Apple Health and OwnTracks
    webhooks check their own key.)

    Also skips the check when no key is configured (first-run, no .env).
    """
    client = request.client
    direct = (
        client is not None
        and client.host in _LOOPBACK_HOSTS
        and "x-forwarded-for" not in request.headers
    )
    # ponytail: any tailnet user is trusted; pin to one login if the tailnet gains others.
    if direct or request.headers.get("tailscale-user-login"):
        return

    effective = settings.effective_admin_key
    if not effective:
        return  # no key configured — open (local dev only)
    if key != effective:
        raise HTTPException(status_code=401, detail="invalid key")
