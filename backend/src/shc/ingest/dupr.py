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


def _parse_match_hit(hit: dict, user_id: int) -> dict[str, Any] | None:
    """Extract structured row from a raw DUPR match history hit.

    Returns None if the user is not found in either team (data sanity guard).
    """
    teams = hit.get("teams") or []
    my_team = next(
        (
            t
            for t in teams
            if any(
                (p or {}).get("id") == user_id
                for p in [t.get("player1"), t.get("player2")]
            )
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


async def sync_matches() -> dict[str, Any]:
    """Fetch full DUPR match history and upsert into dupr_matches.

    Pulls up to 200 matches (all known history). offset=0 is required by the
    API — omitting it returns empty hits even when total > 0.
    """
    token = load_token("dupr", "access_token")
    async with httpx.AsyncClient() as client:
        if not token:
            token = await _login(client)

        # Get user_id — retry once on expired token
        resp = await _get_profile(client, token)
        if resp.status_code in (401, 403):
            token = await _login(client)
            resp = await _get_profile(client, token)
        resp.raise_for_status()
        user_id: int = (resp.json().get("result") or {}).get("id") or 0

        # Fetch match history — limit=25 is the practical max the API returns
        # non-empty results for; offset=0 is required (omitting it yields 0 hits)
        all_hits: list[dict] = []
        for offset in range(0, 500, 25):
            r = await client.post(
                f"{DUPR_BASE}/match/{_VERSION}/history/",
                json={"playerId": user_id, "limit": 25, "offset": offset},
                headers={"Authorization": f"Bearer {token}"},
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
                    "mid": r["match_id"], "ed": r["event_date"], "en": r["event_name"],
                    "v": r["venue"], "fmt": r["format"],
                    "pn": r["partner_name"], "o1": r["opponent1_name"], "o2": r["opponent2_name"],
                    "won": r["won"],
                    "g1u": r["game1_us"], "g1t": r["game1_them"],
                    "g2u": r["game2_us"], "g2t": r["game2_them"],
                    "g3u": r["game3_us"], "g3t": r["game3_them"],
                    "dpre": r["dupr_pre"], "dpost": r["dupr_post"], "ddelta": r["dupr_delta"],
                    "raw": r["raw"],
                },
            )

    log.info("DUPR match sync: upserted %d matches", len(rows))
    return {"synced": len(rows), "total_api": len(hits)}


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
