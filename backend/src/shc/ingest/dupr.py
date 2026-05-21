"""Pull the current DUPR rating from the unofficial DUPR backend API.

DUPR has no self-serve public API; this talks to the same backend the mobile and
web apps use (``api.dupr.gg``), authenticating with the account's own email and
password to obtain a bearer token. The token is cached in the macOS Keychain and
refreshed on a 401/403. One rating snapshot is stored per calendar day in
``dupr_snapshots`` so the goal scorecard can plot the trajectory toward 5.0.

Credentials resolve from Keychain first (``shc.dupr.email`` / ``shc.dupr.password``),
then from the ``DUPR_EMAIL`` / ``DUPR_PASSWORD`` env vars. This is an unofficial
endpoint: it can change without notice and is intended for personal single-user use.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

import httpx

from shc.auth.keychain import load_token, store_token
from shc.config import settings
from shc.db.schema import write_ctx

log = logging.getLogger(__name__)

DUPR_BASE = "https://api.dupr.gg"
_VERSION = "v1.0"
_TIMEOUT = 30.0


def _credentials() -> tuple[str, str]:
    email = load_token("dupr", "email") or settings.dupr_email
    password = load_token("dupr", "password") or settings.dupr_password
    if not email or not password:
        raise RuntimeError(
            "DUPR credentials not found — set DUPR_EMAIL and DUPR_PASSWORD in "
            "backend/.env (or store them in Keychain as shc.dupr.email / shc.dupr.password)"
        )
    return email, password


def _to_float(value: Any) -> float | None:
    """DUPR returns ratings as strings, with "NR" for not-yet-rated."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.upper() in ("", "NR", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_ratings(result: dict) -> tuple[float | None, float | None, bool | None, bool | None]:
    """Pull (doubles, singles, doubles_provisional, singles_provisional) from a profile result."""
    stats = result.get("stats") or {}
    doubles = _to_float(stats.get("doubles"))
    singles = _to_float(stats.get("singles"))
    doubles_prov = stats.get("doublesProvisional")
    singles_prov = stats.get("singlesProvisional")
    return doubles, singles, doubles_prov, singles_prov


async def _login(client: httpx.AsyncClient) -> str:
    email, password = _credentials()
    log.debug("DUPR login for %s", email)
    resp = await client.post(
        f"{DUPR_BASE}/auth/{_VERSION}/login/",
        json={"email": email, "password": password},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    token = (resp.json().get("result") or {}).get("accessToken")
    if not token:
        raise RuntimeError("DUPR login succeeded but returned no access token")
    store_token("dupr", "access_token", token)
    return token


async def _get_profile(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.get(
        f"{DUPR_BASE}/user/{_VERSION}/profile/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )


async def _mark_state(*, needs_reauth: bool) -> None:
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO oauth_state (source, last_sync_at, needs_reauth)
            VALUES ('dupr', $ts, $reauth)
            ON CONFLICT (source) DO UPDATE SET
                last_sync_at = EXCLUDED.last_sync_at,
                needs_reauth = EXCLUDED.needs_reauth
            """,
            {"ts": datetime.now(UTC).isoformat(), "reauth": needs_reauth},
        )


async def _upsert_snapshot(
    doubles: float | None,
    singles: float | None,
    doubles_prov: bool | None,
    singles_prov: bool | None,
    raw: dict,
) -> None:
    today = date.today().isoformat()
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO dupr_snapshots
                (date, doubles, singles, doubles_provisional, singles_provisional, raw, synced_at)
            VALUES ($d, $db, $si, $dp, $sp, $raw, now())
            ON CONFLICT (date) DO UPDATE SET
                doubles = EXCLUDED.doubles,
                singles = EXCLUDED.singles,
                doubles_provisional = EXCLUDED.doubles_provisional,
                singles_provisional = EXCLUDED.singles_provisional,
                raw = EXCLUDED.raw,
                synced_at = EXCLUDED.synced_at
            """,
            {
                "d": today,
                "db": doubles,
                "si": singles,
                "dp": doubles_prov,
                "sp": singles_prov,
                "raw": json.dumps(raw),
            },
        )


async def sync_rating() -> dict[str, Any]:
    """Fetch the current DUPR rating and upsert today's snapshot.

    Returns the parsed doubles/singles rating. Raises RuntimeError on missing
    credentials and httpx.HTTPStatusError on an unrecoverable API error (after
    flagging the source as needing re-auth).
    """
    token = load_token("dupr", "access_token")
    async with httpx.AsyncClient() as client:
        if not token:
            token = await _login(client)
        resp = await _get_profile(client, token)
        if resp.status_code in (401, 403):
            log.info("DUPR token rejected (%s) — re-authenticating", resp.status_code)
            token = await _login(client)
            resp = await _get_profile(client, token)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            await _mark_state(needs_reauth=True)
            raise
        result = resp.json().get("result") or {}

    doubles, singles, doubles_prov, singles_prov = _extract_ratings(result)
    await _upsert_snapshot(doubles, singles, doubles_prov, singles_prov, result)
    await _mark_state(needs_reauth=False)
    log.info("DUPR sync complete: doubles=%s singles=%s", doubles, singles)
    return {"doubles": doubles, "singles": singles}
