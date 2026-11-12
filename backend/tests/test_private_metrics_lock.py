from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import duckdb
import pytest

from shc.ingest import whoop_private_metrics as m


@pytest.mark.asyncio
async def test_network_fetches_finish_before_the_write_lock_is_taken(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    async def stress(day):  # noqa: ANN001, ANN202
        events.append("fetch")
        return {
            "samples": [(datetime(2026, 1, 1, 12, tzinfo=UTC), 1.0, "low")],
            "stress_score": 1.0,
        }

    async def need() -> dict:
        events.append("fetch")
        return {}

    async def none() -> None:
        events.append("fetch")

    async def empty() -> list:
        events.append("fetch")
        return []

    @asynccontextmanager
    async def fake_write_ctx():  # noqa: ANN202
        events.append("lock")
        yield conn

    monkeypatch.setattr(m, "sync_stress", stress)
    monkeypatch.setattr(m, "sync_sleep_need", need)
    monkeypatch.setattr(m, "sync_sleeping_hr_baseline", none)
    monkeypatch.setattr(m, "sync_hr_zones", empty)
    monkeypatch.setattr(m, "sync_behavior_impact", empty)
    monkeypatch.setattr("shc.db.schema.write_ctx", fake_write_ctx)

    result = await m.sync_private_metrics(days=3)

    assert events.count("lock") == 1
    assert events.index("lock") == len(events) - 1
    assert result["stress_days"] == 3
