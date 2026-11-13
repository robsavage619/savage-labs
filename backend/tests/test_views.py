"""Screen views collapse to their surface, so sub-routes and queries don't split counts."""

from __future__ import annotations

from shc.api.routers.views import surface_of


def test_routes_collapse_to_surface() -> None:
    assert surface_of("/") == "/"
    assert surface_of("/lab") == "/lab"
    assert surface_of("/lab/trial/3?tab=x") == "/lab"
    assert surface_of("/?q=1") == "/"
