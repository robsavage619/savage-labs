"""A failed re-upload must leave the stored photo for that date and angle untouched."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shc.api.deps import require_admin_key
from shc.api.routers import progress_photos


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def unreadable(_path: Path, baseline_scale_px: float | None = None) -> None:
        raise ValueError("no pose detected in image")

    monkeypatch.setattr(
        progress_photos, "_vision", lambda: (SimpleNamespace(analyze_photo=unreadable), None)
    )
    monkeypatch.setattr(progress_photos, "_photo_dir", lambda: tmp_path)
    monkeypatch.setattr(progress_photos, "_baseline_scale", lambda _angle: None)
    app = FastAPI()
    app.include_router(progress_photos.router, prefix="/api")
    app.dependency_overrides[require_admin_key] = lambda: None
    return TestClient(app)


def test_failed_reupload_keeps_the_stored_photo(client: TestClient, tmp_path: Path) -> None:
    stored = tmp_path / "2026-05-25_front.jpg"
    stored.write_bytes(b"the good photo")

    response = client.post(
        "/api/progress-photos",
        data={"photo_date": "2026-05-25", "angle": "front"},
        files={"file": ("retake.jpg", b"not a body", "image/jpeg")},
    )

    assert response.status_code == 422
    assert stored.read_bytes() == b"the good photo"
    assert [p.name for p in tmp_path.iterdir()] == [stored.name], "no upload debris left behind"
