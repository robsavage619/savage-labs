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
import re
from datetime import UTC, date, datetime
from http.cookies import CookieError, SimpleCookie
from typing import Any

import httpx

from shc.auth.keychain import load_token, store_token
from shc.config import settings
from shc.db.schema import write_ctx

log = logging.getLogger(__name__)

DUPR_BASE = "https://api.dupr.gg"
_VERSION = "v1.0"
_TIMEOUT = 30.0


def _base() -> str:
    """The host that issued our session: the one that accepted the emailed code, else the default."""
    return load_token("dupr", "base_url") or DUPR_BASE


def _auth_headers(token: str) -> dict[str, str]:
    """The session as DUPR's clients present it: a Bearer header and the access cookie."""
    return {"Authorization": f"Bearer {token}", "Cookie": f"__Host-dupr_at={token}"}


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


class DuprVerificationRequired(RuntimeError):
    """DUPR refused a password login and wants action before issuing a token."""


async def _login_paused() -> bool:
    async with write_ctx() as conn:
        row = conn.execute("SELECT needs_reauth FROM oauth_state WHERE source = 'dupr'").fetchone()
    return bool(row and row[0])


async def _login(client: httpx.AsyncClient, *, force: bool = False) -> str:
    # Each password login makes DUPR email Rob a verification code this client
    # cannot submit. Once a login is refused, only a deliberate manual sync may
    # retry; otherwise every scheduled or sync/all run sends another email.
    if not force and await _login_paused():
        raise DuprVerificationRequired(
            "DUPR logins are paused until the account is re-verified — log in at "
            "dupr.gg, then run a manual DUPR sync"
        )
    email, password = _credentials()
    log.debug("DUPR login for %s", email)
    resp = await client.post(
        f"{DUPR_BASE}/auth/{_VERSION}/login/",
        json={"email": email, "password": password},
        timeout=_TIMEOUT,
    )
    if resp.status_code == 428:
        # Keep what DUPR said: the status alone never told us what it wants.
        # The challenge token is a credential for the emailed code; never keep it.
        try:
            challenge = (resp.json() or {}).get("challengeToken")
        except ValueError:
            challenge = None
        if challenge:
            store_token("dupr", "challenge_token", challenge)
        said = re.sub(r'("challengeToken"\s*:\s*")[^"]*"', r'\1<REDACTED>"', resp.text.strip())[
            :300
        ]
        log.warning("DUPR login refused with 428: %s", said or "(empty body)")
        await _mark_state(needs_reauth=True, error=f"428: {said}" if said else "428")
        raise DuprVerificationRequired(
            "DUPR login needs an emailed verification code, which this client cannot "
            f"submit — automatic DUPR logins are paused. DUPR said: {said or '(empty body)'}"
        )
    if resp.status_code in (401, 403):
        # The stored email/password itself is bad — this is the one failure
        # that genuinely needs Rob to do something, so it is the one that
        # raises the banner. A 5xx here falls through to raise_for_status
        # without touching the flag.
        await _mark_state(needs_reauth=True)
    resp.raise_for_status()
    result = resp.json().get("result") or {}
    # Field names only, never values: shows whether login also issues a longer-lived token.
    log.info("DUPR login ok; result fields: %s", sorted(result))
    token = result.get("accessToken")
    if not token:
        raise RuntimeError("DUPR login succeeded but returned no access token")
    store_token("dupr", "access_token", token)
    return token


def _cookie_tokens(resp: httpx.Response) -> tuple[str | None, str | None, list[str]]:
    """(access, refresh, cookie names) from a response's Set-Cookie headers, matched by name.

    DUPR's web client receives its tokens as cookies, not in the body. They are parsed
    from the raw headers because their Domain need not match the host we called, which
    httpx's cookie jar would drop.
    """
    jar: dict[str, str] = {}
    for header in resp.headers.get_list("set-cookie"):
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(header)
        except CookieError:
            continue
        jar.update({name: morsel.value for name, morsel in cookie.items()})

    def pick(word: str, suffix: str) -> str | None:
        # DUPR's own cookies are __Host-dupr_at (access) and __Host-dupr_rt (refresh).
        return next(
            (v for k, v in jar.items() if word in k.lower() or k.lower().endswith(suffix)), None
        )

    return pick("access", "_at"), pick("refresh", "_rt"), sorted(jar)


def _extract_tokens(resp: httpx.Response) -> tuple[str | None, str | None]:
    """(access, refresh) from a login, verify or refresh response, body or cookies.

    Field and cookie names are logged, never values, so a surprise shows up.
    """
    try:
        body = resp.json()
    except ValueError:
        body = {}
    node = body.get("result") if isinstance(body.get("result"), dict) else body
    node = node if isinstance(node, dict) else {}
    c_access, c_refresh, names = _cookie_tokens(resp)
    log.info("DUPR response fields: %s; cookies: %s", sorted(node), names)
    return node.get("accessToken") or c_access, node.get("refreshToken") or c_refresh


async def _refresh(client: httpx.AsyncClient) -> str | None:
    """Renew the session from the stored refresh token, as DUPR's own web client does.

    GET /auth/v1.0/refresh with the token in `x-refresh-token` (shape taken from the
    script on dupr.gg). Returns a fresh access token, or None when there is no refresh
    token or DUPR refused it. A rotated refresh token is stored before anything else
    uses the new access token, so a crash cannot strand the chain.
    """
    refresh = load_token("dupr", "refresh_token")
    if not refresh:
        return None
    resp = await client.get(
        f"{_base()}/auth/{_VERSION}/refresh",
        # The page script sends the header; the dashboard sends the cookie. Send both.
        headers={
            "Accept": "application/json",
            "x-refresh-token": refresh,
            "Cookie": f"__Host-dupr_rt={refresh}",
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        log.warning("DUPR refresh refused (%s)", resp.status_code)
        return None
    access, new_refresh = _extract_tokens(resp)
    if not access:
        log.warning("DUPR refresh returned 200 but no access token")
        return None
    if new_refresh:
        store_token("dupr", "refresh_token", new_refresh)
    store_token("dupr", "access_token", access)
    return access


async def _session_token(
    client: httpx.AsyncClient, *, force_login: bool, renew: bool = False
) -> str:
    """A usable access token: the cached one, else a refresh, else a password login."""
    if not renew:
        cached = load_token("dupr", "access_token")
        if cached:
            return cached
    return await _refresh(client) or await _login(client, force=force_login)


async def request_code() -> dict[str, Any]:
    """Start a password login. DUPR emails a 6-digit code and returns a challenge token,
    which is kept for `verify_code`. Returns `code_sent`, or the sync result if DUPR
    signed in without asking."""
    async with httpx.AsyncClient() as client:
        try:
            await _login(client, force=True)
        except DuprVerificationRequired:
            if load_token("dupr", "challenge_token"):
                return {"status": "code_sent"}
            raise
    return {"status": "signed_in", **await sync_rating()}


# The web client calls api.dupr.com; this client has always used api.dupr.gg. Try ours first.
_VERIFY_HOSTS = (DUPR_BASE, "https://api.dupr.com")


async def verify_code(code: str) -> dict[str, Any]:
    """Submit the emailed code with the stored challenge token, keep the session DUPR
    returns, and sync. After this the sync renews itself from the refresh token."""
    challenge = load_token("dupr", "challenge_token")
    if not challenge:
        raise DuprVerificationRequired("No code was requested — ask for a new one first")
    async with httpx.AsyncClient() as client:
        resp = None
        for host in _VERIFY_HOSTS:
            resp = await client.post(
                f"{host}/auth/{_VERSION}/2fa/verify",
                json={"challengeToken": challenge, "code": code.strip()},
                timeout=_TIMEOUT,
            )
            if resp.status_code != 404:
                break
        assert resp is not None
        if resp.status_code != 200:
            said = re.sub(r'("challengeToken"\s*:\s*")[^"]*"', r'\1<REDACTED>"', resp.text)[:200]
            log.warning("DUPR code verify refused (%s): %s", resp.status_code, said)
            raise DuprVerificationRequired(f"DUPR refused the code ({resp.status_code}): {said}")
        access, refresh = _extract_tokens(resp)
        if not access:
            names = _cookie_tokens(resp)[2]
            raise DuprVerificationRequired(
                f"DUPR accepted the code but returned no access token; cookies seen: {names}"
            )
        store_token("dupr", "access_token", access)
        if refresh:
            store_token("dupr", "refresh_token", refresh)
        store_token("dupr", "base_url", host)
        store_token("dupr", "challenge_token", "")  # single use
        # Check the session before syncing. A refused session must say so here: letting
        # the sync fall back to a password login would email another code and replace
        # the challenge. The pause flag stays set until a sync actually succeeds.
        check = await _get_profile(client, access)
        if check.status_code != 200:
            raise DuprVerificationRequired(
                f"DUPR accepted the code (via {host}) but then refused the session "
                f"on the profile call ({check.status_code}); cookies seen: {_cookie_tokens(resp)[2]}"
            )
    return await sync_rating()


async def _get_profile(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.get(
        f"{_base()}/user/{_VERSION}/profile/",
        headers=_auth_headers(token),
        timeout=_TIMEOUT,
    )


async def _mark_state(*, needs_reauth: bool, error: str | None = None) -> None:
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO oauth_state (source, last_sync_at, needs_reauth, last_error, last_error_at)
            VALUES ('dupr', $ts, $reauth, $err, CASE WHEN $err IS NULL THEN NULL ELSE $ts END)
            ON CONFLICT (source) DO UPDATE SET
                last_sync_at = EXCLUDED.last_sync_at,
                needs_reauth = EXCLUDED.needs_reauth,
                last_error = EXCLUDED.last_error,
                last_error_at = EXCLUDED.last_error_at
            """,
            {"ts": datetime.now(UTC).isoformat(), "reauth": needs_reauth, "err": error},
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


def _parse_match_hit(hit: dict, user_id: int) -> dict[str, Any] | None:
    """Extract structured row from a raw DUPR match history hit.

    Returns None if the user is not found in either team (data sanity guard).
    """
    teams = hit.get("teams") or []
    my_team = next(
        (
            t
            for t in teams
            if any((p or {}).get("id") == user_id for p in [t.get("player1"), t.get("player2")])
        ),
        None,
    )
    if my_team is None:
        return None
    opp_team = next((t for t in teams if t is not my_team), None)

    is_p1 = ((my_team.get("player1") or {}).get("id")) == user_id
    me = my_team["player1"] if is_p1 else my_team["player2"]
    partner = my_team["player2"] if is_p1 else my_team["player1"]
    p_suffix = "Player1" if is_p1 else "Player2"

    imp = my_team.get("preMatchRatingAndImpact") or {}
    dupr_pre = _to_float(imp.get(f"preMatchDoubleRating{p_suffix}"))
    dupr_delta = _to_float(imp.get(f"matchDoubleRatingImpact{p_suffix}"))
    dupr_post = _to_float((me.get("postMatchRating") or {}).get("doubles"))

    # Per-game scores — skip unplayed games (value == -1)
    games: list[tuple[int, int]] = []
    if opp_team:
        for i in range(1, 4):
            us = my_team.get(f"game{i}", -1)
            them = opp_team.get(f"game{i}", -1)
            if us is not None and them is not None and us >= 0 and them >= 0:
                games.append((int(us), int(them)))

    opp1 = ((opp_team or {}).get("player1") or {}).get("fullName")
    opp2 = ((opp_team or {}).get("player2") or {}).get("fullName")

    return {
        "match_id": hit["matchId"],
        "event_date": hit["eventDate"],
        "event_name": hit.get("league") or hit.get("eventName"),
        "venue": hit.get("venue") or hit.get("location"),
        "format": hit.get("eventFormat", "DOUBLES"),
        "partner_name": (partner or {}).get("fullName"),
        "opponent1_name": opp1,
        "opponent2_name": opp2,
        "won": bool(my_team.get("winner")),
        "game1_us": games[0][0] if len(games) > 0 else None,
        "game1_them": games[0][1] if len(games) > 0 else None,
        "game2_us": games[1][0] if len(games) > 1 else None,
        "game2_them": games[1][1] if len(games) > 1 else None,
        "game3_us": games[2][0] if len(games) > 2 else None,
        "game3_them": games[2][1] if len(games) > 2 else None,
        "dupr_pre": dupr_pre,
        "dupr_post": dupr_post,
        "dupr_delta": dupr_delta,
        "raw": json.dumps(hit),
    }


async def sync_matches(*, force_login: bool = False) -> dict[str, Any]:
    """Fetch full DUPR match history and upsert into dupr_matches.

    Pulls up to 200 matches (all known history). offset=0 is required by the
    API — omitting it returns empty hits even when total > 0.
    """
    async with httpx.AsyncClient() as client:
        token = await _session_token(client, force_login=force_login)

        # Get user_id — retry once on expired token
        resp = await _get_profile(client, token)
        if resp.status_code in (401, 403):
            token = await _session_token(client, force_login=force_login, renew=True)
            resp = await _get_profile(client, token)
        resp.raise_for_status()
        user_id: int = (resp.json().get("result") or {}).get("id") or 0

        # Fetch match history — limit=25 is the practical max the API returns
        # non-empty results for; offset=0 is required (omitting it yields 0 hits)
        all_hits: list[dict] = []
        for offset in range(0, 500, 25):
            r = await client.post(
                f"{_base()}/match/{_VERSION}/history/",
                json={"playerId": user_id, "limit": 25, "offset": offset},
                headers=_auth_headers(token),
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            result = r.json().get("result") or {}
            hits_page = result.get("hits") or []
            all_hits.extend(hits_page)
            if not result.get("hasMore") or not hits_page:
                break

        hits = all_hits

    rows = [_parse_match_hit(h, user_id) for h in hits]
    rows = [r for r in rows if r is not None]

    async with write_ctx() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT INTO dupr_matches (
                    match_id, event_date, event_name, venue, format,
                    partner_name, opponent1_name, opponent2_name, won,
                    game1_us, game1_them, game2_us, game2_them,
                    game3_us, game3_them,
                    dupr_pre, dupr_post, dupr_delta, raw, synced_at
                ) VALUES (
                    $mid, $ed, $en, $v, $fmt,
                    $pn, $o1, $o2, $won,
                    $g1u, $g1t, $g2u, $g2t,
                    $g3u, $g3t,
                    $dpre, $dpost, $ddelta, $raw, now()
                )
                ON CONFLICT (match_id) DO UPDATE SET
                    event_date = EXCLUDED.event_date,
                    event_name = EXCLUDED.event_name,
                    won = EXCLUDED.won,
                    game1_us = EXCLUDED.game1_us, game1_them = EXCLUDED.game1_them,
                    game2_us = EXCLUDED.game2_us, game2_them = EXCLUDED.game2_them,
                    game3_us = EXCLUDED.game3_us, game3_them = EXCLUDED.game3_them,
                    dupr_pre = EXCLUDED.dupr_pre,
                    dupr_post = EXCLUDED.dupr_post,
                    dupr_delta = EXCLUDED.dupr_delta,
                    raw = EXCLUDED.raw,
                    synced_at = EXCLUDED.synced_at
                """,
                {
                    "mid": r["match_id"],
                    "ed": r["event_date"],
                    "en": r["event_name"],
                    "v": r["venue"],
                    "fmt": r["format"],
                    "pn": r["partner_name"],
                    "o1": r["opponent1_name"],
                    "o2": r["opponent2_name"],
                    "won": r["won"],
                    "g1u": r["game1_us"],
                    "g1t": r["game1_them"],
                    "g2u": r["game2_us"],
                    "g2t": r["game2_them"],
                    "g3u": r["game3_us"],
                    "g3t": r["game3_them"],
                    "dpre": r["dupr_pre"],
                    "dpost": r["dupr_post"],
                    "ddelta": r["dupr_delta"],
                    "raw": r["raw"],
                },
            )

    log.info("DUPR match sync: upserted %d matches", len(rows))
    return {"synced": len(rows), "total_api": len(hits)}


async def sync_rating(*, force_login: bool = False) -> dict[str, Any]:
    """Fetch the current DUPR rating and upsert today's snapshot.

    Returns the parsed doubles/singles rating. Raises RuntimeError on missing
    credentials and httpx.HTTPStatusError on an unrecoverable API error.

    Only a rejected credential (a 401/403 that survives a fresh login) sets
    `needs_reauth`. A 5xx does not: api.dupr.gg is an unofficial endpoint that
    returns bare nginx 503s during its own outages, and on 2026-09-06 one of
    those raised the reauth banner over an API Rob had no way to fix and a
    "Reconnect" link that 404s. Same rule whoop.py already follows.
    """
    async with httpx.AsyncClient() as client:
        token = await _session_token(client, force_login=force_login)
        resp = await _get_profile(client, token)
        if resp.status_code in (401, 403):
            log.info("DUPR token rejected (%s) — renewing", resp.status_code)
            token = await _session_token(client, force_login=force_login, renew=True)
            resp = await _get_profile(client, token)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # A 401/403 here already survived the re-login above, so the stored
            # credentials really are bad. Anything else (5xx, 429, gateway HTML)
            # is DUPR's problem, not Rob's — log it, leave the flag alone.
            if resp.status_code in (401, 403):
                await _mark_state(needs_reauth=True)
            else:
                log.warning("DUPR profile fetch failed transiently (%s)", resp.status_code)
            raise
        result = resp.json().get("result") or {}

    doubles, singles, doubles_prov, singles_prov = _extract_ratings(result)
    await _upsert_snapshot(doubles, singles, doubles_prov, singles_prov, result)
    await _mark_state(needs_reauth=False)
    log.info("DUPR sync complete: doubles=%s singles=%s", doubles, singles)
    return {"doubles": doubles, "singles": singles}
