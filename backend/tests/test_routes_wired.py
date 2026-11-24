"""A router that exists but is not mounted serves nothing, and nothing says so."""

from __future__ import annotations

import pytest

from shc.api.main import app

_PATHS = {
    "/api/model",
    "/api/healthspan",
    "/api/experiments/block",
    "/api/research/beliefs",
}


@pytest.mark.parametrize("path", sorted(_PATHS))
def test_route_is_mounted(path: str) -> None:
    assert path in {getattr(r, "path", None) for r in app.routes}
