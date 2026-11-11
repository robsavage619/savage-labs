"""The iCloud inbox that lets the phone's daily Shortcut export land while the Mac sleeps."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb

from shc.api.routers import apple


def _patch_db(conn: duckdb.DuckDBPyConnection, monkeypatch) -> None:
    @asynccontextmanager
    async def _write_ctx():
        yield conn

    monkeypatch.setattr(apple, "write_ctx", _write_ctx)


async def test_inbox_ingests_and_archives(conn, monkeypatch, tmp_path: Path) -> None:
    _patch_db(conn, monkeypatch)
    payload = {
        "date": "2026-11-08",
        "metrics": {"step_count": 9899, "walking_speed_mph": 2.6, "basal_energy_kcal": 1800},
    }
    (tmp_path / "2026-11-08.json").write_text(json.dumps(payload))

    assert await apple.ingest_shortcut_inbox(tmp_path) == 1

    rows = conn.execute(
        "SELECT metric, value_num FROM measurements WHERE source = 'apple_health' ORDER BY metric"
    ).fetchall()
    assert rows == [
        ("basal_energy_kcal", 1800.0),
        ("step_count", 9899.0),
        ("walking_speed_m_s", round(2.6 * 0.44704, 4)),
    ]
    assert not (tmp_path / "2026-11-08.json").exists()
    assert (tmp_path / "processed" / "2026-11-08.json").exists()


async def test_inbox_quarantines_bad_file(conn, monkeypatch, tmp_path: Path) -> None:
    _patch_db(conn, monkeypatch)
    (tmp_path / "broken.json").write_text("{not json")

    assert await apple.ingest_shortcut_inbox(tmp_path) == 0

    assert (tmp_path / "failed" / "broken.json").exists()
    assert conn.execute("SELECT count(*) FROM measurements").fetchone() == (0,)


async def test_inbox_missing_dir_is_noop(tmp_path: Path) -> None:
    assert await apple.ingest_shortcut_inbox(tmp_path / "absent") == 0
