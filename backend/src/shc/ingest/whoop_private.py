"""Client for WHOOP's private iOS API (AWS Cognito auth via WHOOP's own proxy).

This is a SEPARATE surface from `ingest.whoop`, which speaks the public OAuth
developer API. The public API exposes 13 read-only endpoints and deliberately
omits the Journal; this one reaches the behavior journal the iOS app writes.

Wire format reverse-engineered by the Totem project (MIT, github.com/thebriangao/totem).
Using it is contrary to WHOOP's Terms of Use §4(iii) and §4(v) and WHOOP may
suspend the account under §21 — this module exists because Rob made that call
explicitly, not because it is sanctioned.

Credentials: the account password is NEVER stored. `login()` takes it, exchanges
it for Cognito tokens, and discards it; only the resulting tokens land in the
macOS Keychain alongside the OAuth ones.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from shc.auth.keychain import load_token, store_token

log = logging.getLogger(__name__)

_SOURCE = "whoop_private"
_BASE = "https://api.prod.whoop.com"
_AUTH_PATH = "/auth-service/v3/whoop/"

# CloudFlare fronts the Cognito proxy and 403s any client missing the iOS AWS
# SDK fingerprint — these strings are load-bearing, not cosmetic. A Node/Python
# default User-Agent is rejected outright.
_AWS_SDK_UA = (
    "aws-sdk-swift/1.5.86 ua/2.1 api/cognito_identity_provider#1.5.86 "
    "os/ios#26.3.1 lang/swift#5.10 m/D,N,Z,b"
)
_IOS_APP_VERSION = "5.52.0"
_IOS_BUILD_NUMBER = "595097"
_IOS_TIME_ZONE = "America/Los_Angeles"

# The proxy injects the real ClientId and computes SECRET_HASH server-side, so
# the app (and therefore we) send an empty string here.
_CLIENT_ID = ""

_ACCESS_TOKEN_SAFETY_MARGIN_S = 300

_refresh_lock = asyncio.Lock()


class WHOOPPrivateAuthError(RuntimeError):
    """Raised when the Cognito session is dead and an interactive re-login is required."""


class WHOOPPrivateSchemaError(RuntimeError):
    """Raised when a private-API response omits fields we depend on — fails loud, never silent."""


def _installation_id() -> str:
    """Return the stable per-install UUID the iOS app sends on every data request.

    Generated once and persisted, because a value that changes per request is a
    louder fingerprint than a constant one.
    """
    existing = load_token(_SOURCE, "installation_id")
    if existing:
        return existing
    generated = str(uuid.uuid4())
    store_token(_SOURCE, "installation_id", generated)
    log.info("generated WHOOP private-API installation identifier")
    return generated


async def _cognito(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST one AWS Cognito operation through WHOOP's auth proxy."""
    headers = {
        "content-type": "application/x-amz-json-1.1",
        "x-amz-target": f"AWSCognitoIdentityProviderService.{operation}",
        "amz-sdk-invocation-id": str(uuid.uuid4()),
        "amz-sdk-request": "attempt=1; max=1",
        "user-agent": _AWS_SDK_UA,
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_BASE + _AUTH_PATH, content=json.dumps(payload), headers=headers)

    if resp.status_code in (400, 401, 403):
        # Deliberately does not echo the response body — it can contain the
        # submitted username and Cognito error detail.
        raise WHOOPPrivateAuthError(
            f"WHOOP private-API {operation} rejected ({resp.status_code}) — re-login required"
        )
    resp.raise_for_status()
    return resp.json()


def _store_auth_result(result: dict[str, Any]) -> None:
    """Persist Cognito tokens to the Keychain."""
    access = result.get("AccessToken")
    if not access:
        raise WHOOPPrivateSchemaError(
            "Cognito response carried no AccessToken — auth shape changed, investigate"
        )
    store_token(_SOURCE, "access_token", access)

    # REFRESH_TOKEN_AUTH does NOT return a new RefreshToken (Cognito doesn't
    # rotate on this flow). Only overwrite when one is actually present, or a
    # refresh would wipe the working token and force a full re-login.
    if result.get("RefreshToken"):
        store_token(_SOURCE, "refresh_token", result["RefreshToken"])

    expires_in = int(result.get("ExpiresIn", 86400))
    expiry = datetime.now(UTC).timestamp() + expires_in - _ACCESS_TOKEN_SAFETY_MARGIN_S
    store_token(_SOURCE, "access_expiry", str(expiry))


async def login(email: str, password: str, mfa_code_provider: Any = None) -> None:
    """Establish a private-API session from account credentials.

    Args:
        email: WHOOP account email.
        password: Account password. Used only for this exchange, never persisted.
        mfa_code_provider: Callable taking the masked delivery destination and
            returning the 6-digit code. Required if the account has MFA enabled.

    Raises:
        WHOOPPrivateAuthError: Credentials rejected, or an MFA challenge arrived
            with no way to answer it.
    """
    init = await _cognito(
        "InitiateAuth",
        {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": {"USERNAME": email, "PASSWORD": password},
            "ClientId": _CLIENT_ID,
        },
    )

    challenge = init.get("ChallengeName")
    if challenge in ("SMS_MFA", "SOFTWARE_TOKEN_MFA"):
        if mfa_code_provider is None:
            raise WHOOPPrivateAuthError(f"{challenge} required but no MFA code provider supplied")
        code_field = "SMS_MFA_CODE" if challenge == "SMS_MFA" else "SOFTWARE_TOKEN_MFA_CODE"
        destination = init.get("ChallengeParameters", {}).get("CODE_DELIVERY_DESTINATION", "")
        answered = await _cognito(
            "RespondToAuthChallenge",
            {
                "ChallengeName": challenge,
                "ChallengeResponses": {
                    "USERNAME": email,
                    code_field: mfa_code_provider(destination),
                },
                "ClientId": _CLIENT_ID,
                "Session": init.get("Session", ""),
            },
        )
        result = answered.get("AuthenticationResult") or {}
    elif challenge:
        raise WHOOPPrivateAuthError(f"Unsupported Cognito challenge: {challenge}")
    else:
        result = init.get("AuthenticationResult") or {}

    _store_auth_result(result)
    log.info("WHOOP private-API session established")


async def _refresh() -> str:
    """Renew the access token. Serialised so concurrent callers don't race."""
    async with _refresh_lock:
        refresh = load_token(_SOURCE, "refresh_token")
        if not refresh:
            raise WHOOPPrivateAuthError(
                "No WHOOP private-API refresh token — run `shc whoop-private login` first"
            )
        resp = await _cognito(
            "InitiateAuth",
            {
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "AuthParameters": {"REFRESH_TOKEN": refresh},
                "ClientId": _CLIENT_ID,
            },
        )
        result = resp.get("AuthenticationResult") or {}
        _store_auth_result(result)
        log.info("WHOOP private-API token refreshed")
        return result["AccessToken"]


async def _access_token() -> str:
    """Return a valid access token, refreshing if it is missing or near expiry."""
    token = load_token(_SOURCE, "access_token")
    raw_expiry = load_token(_SOURCE, "access_expiry")
    if not token or not raw_expiry:
        return await _refresh()
    try:
        expiry = float(raw_expiry)
    except ValueError:
        return await _refresh()
    if datetime.now(UTC).timestamp() >= expiry:
        return await _refresh()
    return token


def _device_headers(token: str) -> dict[str, str]:
    """Build the iOS app's full identity header set for a data request."""
    return {
        "authorization": f"Bearer {token}",
        "user-agent": "iOS",
        "x-whoop-device-platform": "iOS",
        "x-whoop-ios-version": _IOS_APP_VERSION,
        "x-whoop-ios-build-number": _IOS_BUILD_NUMBER,
        "x-whoop-bundle-name": "com.whoop.iphone",
        "x-whoop-installation-identifier": _installation_id(),
        "x-whoop-time-zone": _IOS_TIME_ZONE,
        "x-whoop-clock-format": "TWELVE_HOUR",
        "currency": "USD",
        "locale": "en_US",
        "accept-language": "en",
        "accept": "*/*",
    }


async def get(path: str, params: dict | None = None) -> dict:
    """GET a private-API path with 401 → refresh and 429 → exponential backoff.

    Mirrors the retry policy of `ingest.whoop._get` so both WHOOP surfaces
    behave the same way under rate limiting.
    """
    token = await _access_token()

    delay = 1.0
    last_resp: httpx.Response | None = None
    for attempt in range(4):
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{_BASE}{path}", params=params, headers=_device_headers(token))
        last_resp = resp
        if resp.status_code == 401:
            token = await _refresh()
            continue
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", delay))
            log.warning(
                "WHOOP private-API 429 on %s — backing off %.1fs (attempt %d/4)",
                path,
                retry_after,
                attempt + 1,
            )
            await asyncio.sleep(retry_after)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()

    assert last_resp is not None
    last_resp.raise_for_status()
    raise RuntimeError(f"WHOOP private-API get exhausted retries on {path}")


def is_linked() -> bool:
    """True if a private-API refresh token exists in the Keychain."""
    return bool(load_token(_SOURCE, "refresh_token"))
