from __future__ import annotations

"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from shc.config import settings

_key_header = APIKeyHeader(name="X-SHC-Key", auto_error=False)


def require_admin_key(key: Annotated[str | None, Depends(_key_header)]) -> None:
    """Reject mutating requests that don't carry the configured admin key.

    Skips the check when no key is configured (local dev with no .env) so
    the first-run experience isn't blocked.  Set SHC_ADMIN_KEY (or
    APPLE_WEBHOOK_KEY) in .env to enforce authentication.
    """
    effective = settings.effective_admin_key
    if not effective:
        return  # no key configured — open (local dev only)
    if key != effective:
        raise HTTPException(status_code=401, detail="invalid key")
