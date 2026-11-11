from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shc.api.middleware import HostOriginMiddleware
from shc.config import settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "tailscale_host", "box.example.ts.net")
    app = FastAPI()
    app.add_middleware(HostOriginMiddleware)

    @app.post("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize(
    ("host", "origin", "status"),
    [
        ("box.example.ts.net", "https://box.example.ts.net", 200),
        (f"127.0.0.1:{settings.port}", "http://localhost:3000", 200),
        ("box.example.ts.net", "https://evil.example.com", 403),
        ("evil.example.com", "https://box.example.ts.net", 403),
    ],
)
def test_tailnet_origin_is_allowed_others_refused(
    client: TestClient, host: str, origin: str, status: int
) -> None:
    r = client.post("/x", headers={"host": host, "origin": origin})
    assert r.status_code == status


def test_null_origin_refused_without_a_tailnet_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tailscale_host", None)
    app = FastAPI()
    app.add_middleware(HostOriginMiddleware)

    @app.post("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    r = TestClient(app).post("/x", headers={"host": "localhost:8000", "origin": "null"})
    assert r.status_code == 403
