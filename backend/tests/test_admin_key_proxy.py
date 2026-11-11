from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shc.api.deps import require_admin_key
from shc.config import settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "shc_admin_key", "k")
    app = FastAPI()

    @app.post("/x")
    def x(_: Annotated[None, Depends(require_admin_key)]) -> dict[str, bool]:
        return {"ok": True}

    # TestClient's peer is "testclient"; pose as loopback like uvicorn would.
    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 200),  # direct loopback: CLI, scheduled sync, SSH tunnel
        ({"X-Forwarded-For": "100.64.0.2", "Tailscale-User-Login": "u@example.com"}, 200),
        ({"X-Forwarded-For": "203.0.113.9"}, 401),  # Funnel / tagged node: no identity
        ({"X-Forwarded-For": "203.0.113.9", "X-SHC-Key": "k"}, 200),
    ],
)
def test_proxied_loopback_needs_tailnet_identity(
    client: TestClient, headers: dict[str, str], status: int
) -> None:
    assert client.post("/x", headers=headers).status_code == status
