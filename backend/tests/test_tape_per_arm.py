"""Per-arm tape readings sit beside the single-arm series without touching it."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

import pytest
from pydantic import ValidationError

from shc.api.routers import dashboard
from shc.api.routers.dashboard import TapeSubmission, post_tape, tape_history


@pytest.fixture
def api(conn, monkeypatch):
    @asynccontextmanager
    async def _write_ctx():
        yield conn

    monkeypatch.setattr(dashboard, "write_ctx", _write_ctx)

    class _Keep:
        execute = staticmethod(conn.execute)

        def close(self) -> None:
            pass

    monkeypatch.setattr(dashboard, "get_read_conn", _Keep)
    return conn


@pytest.mark.asyncio
async def test_left_and_right_round_trip_in_inches(api) -> None:
    out = await post_tape(TapeSubmission(arm_left_in=15.0, arm_right_in=15.5))
    assert out["saved"] == ["arm_left_in", "arm_right_in"]
    today = date.today().isoformat()
    assert tape_history(api) == {
        "arm_left_in": [{"date": today, "inches": 15.0}],
        "arm_right_in": [{"date": today, "inches": 15.5}],
    }
    got = await dashboard.get_tape()
    assert got["arm_left_in"]["inches"] == 15.0
    assert got["arm_right_in"]["readings"] == 1


@pytest.mark.asyncio
async def test_same_day_replaces_per_metric_and_old_arm_is_untouched(api) -> None:
    await post_tape(TapeSubmission(arm_in=14.0, arm_left_in=15.0))
    await post_tape(TapeSubmission(arm_left_in=15.25))
    hist = tape_history(api)
    assert [p["inches"] for p in hist["arm_left_in"]] == [15.25]
    assert [p["inches"] for p in hist["arm_in"]] == [14.0]
    assert "arm_right_in" not in hist


@pytest.mark.asyncio
async def test_old_arm_only_post_writes_no_side_series(api) -> None:
    await post_tape(TapeSubmission(arm_in=14.0))
    assert set(tape_history(api)) == {"arm_in"}


@pytest.mark.parametrize("field", ["arm_left_in", "arm_right_in"])
@pytest.mark.parametrize("bad", [5, 40, 100])
def test_per_arm_bounds_match_arm_in(field, bad) -> None:
    with pytest.raises(ValidationError):
        TapeSubmission(**{field: bad})


def test_side_readings_do_not_enter_the_cadence_check(api) -> None:
    api.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
        "VALUES ('manual','arm_left_circumference_cm','2026-11-20',38.1,'cm','a','a')"
    )
    due = dashboard.measurements_due(api, date(2026, 11, 24))
    assert next(i for i in due["items"] if i["key"] == "tape")["due"] is True
