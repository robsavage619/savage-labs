"""DUPR verification loop: a refused login must stop further automatic logins.

On 2026-09-12 every sync hit a dead cached token, fell back to a password login,
got HTTP 428 (DUPR wants an emailed code), and stored nothing — so the next sync
did the same and Rob got another email each time.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import duckdb
import httpx
import pytest

from shc.ingest import dupr

_PROFILE = {"result": {"id": 1, "stats": {"doubles": "3.60", "singles": "NR"}}}


@pytest.fixture
def dupr_env(conn: duckdb.DuckDBPyConnection, monkeypatch):
    calls: list[str] = []
    responses: dict[str, httpx.Response] = {}
    tokens: dict[str, str] = {"access_token": "stale"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        for prefix, resp in responses.items():
            if request.url.path.startswith(prefix):
                return resp
        return httpx.Response(404)

    real_client = httpx.AsyncClient

    @asynccontextmanager
    async def _write_ctx():
        yield conn

    monkeypatch.setattr(
        dupr.httpx, "AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(dupr, "write_ctx", _write_ctx)
    monkeypatch.setattr(dupr, "load_token", lambda _source, kind: tokens.get(kind))
    monkeypatch.setattr(
        dupr, "store_token", lambda _source, kind, value: tokens.__setitem__(kind, value)
    )
    monkeypatch.setattr(dupr, "_credentials", lambda: ("rob@example.com", "pw"))
    return conn, calls, responses


def _logins(calls: list[str]) -> int:
    return sum(path.startswith("/auth/") for path in calls)


def _needs_reauth(conn: duckdb.DuckDBPyConnection) -> bool:
    row = conn.execute("SELECT needs_reauth FROM oauth_state WHERE source = 'dupr'").fetchone()
    return bool(row and row[0])


def test_428_login_raises_and_pauses_logins(dupr_env):
    conn, calls, responses = dupr_env
    responses["/user/"] = httpx.Response(401)
    responses["/auth/"] = httpx.Response(428)

    with pytest.raises(dupr.DuprVerificationRequired):
        asyncio.run(dupr.sync_rating())

    assert _logins(calls) == 1
    assert _needs_reauth(conn)


def test_paused_state_makes_no_further_login_attempts(dupr_env):
    """This is the email: an automatic sync must not POST to /auth/ again."""
    conn, calls, responses = dupr_env
    responses["/user/"] = httpx.Response(401)
    responses["/auth/"] = httpx.Response(428)

    for _ in range(3):
        with pytest.raises(dupr.DuprVerificationRequired):
            asyncio.run(dupr.sync_rating())
    with pytest.raises(dupr.DuprVerificationRequired):
        asyncio.run(dupr.sync_matches())

    assert _logins(calls) == 1


def test_manual_force_login_still_tries_once(dupr_env):
    conn, calls, responses = dupr_env
    responses["/user/"] = httpx.Response(401)
    responses["/auth/"] = httpx.Response(428)
    with pytest.raises(dupr.DuprVerificationRequired):
        asyncio.run(dupr.sync_rating())

    with pytest.raises(dupr.DuprVerificationRequired):
        asyncio.run(dupr.sync_rating(force_login=True))

    assert _logins(calls) == 2


def test_working_cached_token_clears_the_pause_without_logging_in(dupr_env):
    """A token pasted into Keychain recovers the sync with no email sent."""
    conn, calls, responses = dupr_env
    responses["/user/"] = httpx.Response(401)
    responses["/auth/"] = httpx.Response(428)
    with pytest.raises(dupr.DuprVerificationRequired):
        asyncio.run(dupr.sync_rating())

    responses["/user/"] = httpx.Response(200, json=_PROFILE)
    result = asyncio.run(dupr.sync_rating())

    assert result["doubles"] == 3.6
    assert _logins(calls) == 1
    assert not _needs_reauth(conn)


def test_428_keeps_what_dupr_said(dupr_env):
    conn, calls, responses = dupr_env
    responses["/user/"] = httpx.Response(401)
    responses["/auth/"] = httpx.Response(
        428, text='{"message": "Verify your device", "challengeToken": "abc.def.ghi"}'
    )

    with pytest.raises(dupr.DuprVerificationRequired, match="Verify your device") as exc:
        asyncio.run(dupr.sync_rating())
    assert "abc.def.ghi" not in str(exc.value)

    row = conn.execute("SELECT last_error FROM oauth_state WHERE source = 'dupr'").fetchone()
    assert row is not None and "Verify your device" in row[0]
    assert "abc.def.ghi" not in row[0]  # the challenge token is a credential


@pytest.fixture
def refresh_env(conn: duckdb.DuckDBPyConnection, monkeypatch):
    """A DUPR whose access token has expired but whose refresh token still works."""
    calls: list[tuple[str, str]] = []
    tokens: dict[str, str] = {"access_token": "stale", "refresh_token": "r1"}
    good_refresh = {"value": "r1"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path))
        if path.startswith("/auth/v1.0/refresh"):
            if request.headers.get("x-refresh-token") != good_refresh["value"]:
                return httpx.Response(401)
            return httpx.Response(
                200, json={"result": {"accessToken": "fresh", "refreshToken": "r2"}}
            )
        if path.startswith("/user/"):
            ok = request.headers.get("authorization") == "Bearer fresh"
            return httpx.Response(200, json=_PROFILE) if ok else httpx.Response(401)
        return httpx.Response(428)  # a password login must never be needed here

    real_client = httpx.AsyncClient

    @asynccontextmanager
    async def _write_ctx():
        yield conn

    monkeypatch.setattr(
        dupr.httpx, "AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(dupr, "write_ctx", _write_ctx)
    monkeypatch.setattr(dupr, "load_token", lambda _s, kind: tokens.get(kind))
    monkeypatch.setattr(dupr, "store_token", lambda _s, kind, v: tokens.__setitem__(kind, v))
    monkeypatch.setattr(dupr, "_credentials", lambda: ("rob@example.com", "pw"))
    return conn, calls, tokens, good_refresh


def test_expired_token_renews_from_the_refresh_token_without_a_login(refresh_env):
    """This is the point: no password login, so no emailed code."""
    conn, calls, tokens, _ = refresh_env

    result = asyncio.run(dupr.sync_rating())

    assert result["doubles"] == 3.6
    assert not any(m == "POST" for m, _ in calls)
    assert tokens["access_token"] == "fresh"
    assert tokens["refresh_token"] == "r2"  # the rotated token is kept
    assert not _needs_reauth(conn)


def test_link_adopts_a_refresh_token_and_a_refused_one_restores_the_old(refresh_env):
    conn, calls, tokens, good = refresh_env
    good["value"] = "pasted-token-from-the-browser"

    result = asyncio.run(dupr.link("  pasted-token-from-the-browser  "))
    assert result["doubles"] == 3.6
    assert tokens["refresh_token"] == "r2"

    with pytest.raises(dupr.DuprVerificationRequired, match="refused that refresh token"):
        asyncio.run(dupr.link("a-token-dupr-does-not-recognise"))
    assert tokens["refresh_token"] == "r2"  # the working one is not overwritten
