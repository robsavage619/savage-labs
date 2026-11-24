from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shc import metrics, rob_model
from shc.api.deps import require_admin_key
from shc.api.routers import model as model_router
from shc.stats.noise_floor import swc

NOTES = {"acute-chronic-workload-ratio.md", "sesoi-typical-error-individual-change.md"}


@pytest.fixture(autouse=True)
def _vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rob_model, "valid_citation_filenames", lambda: NOTES)


def _rows(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    return conn.execute("SELECT * EXCLUDE (updated_at) FROM rob_parameters ORDER BY key").fetchall()


def _belief(conn: duckdb.DuckDBPyConnection, source: str) -> str:
    bid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_beliefs (id, claim, outcome, prior_mean, prior_sd, "
        "prior_source, post_mean, post_sd, n_results) VALUES (?,?,?,?,?,?,?,?,?)",
        [bid, "synthetic claim", "sleep_efficiency", 1.0, 0.5, source, 0.8, 0.3, 2],
    )
    return bid


def _hrv(conn: duckdb.DuckDBPyConnection, values: list[float]) -> None:
    for i, v in enumerate(values):
        rid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO recovery (id, source, date, hrv, content_hash) VALUES (?,?,?,?,?)",
            [rid, "test", date.today() - timedelta(days=i + 1), v, rid],
        )


def test_status_rule() -> None:
    assert rob_model.status_for(0, 10) == "prior only"
    assert rob_model.status_for(9, 10) == "learning"
    assert rob_model.status_for(10, 10) == "established"


def test_refresh_is_idempotent(conn, seed) -> None:
    _hrv(conn, [50.0 + (i % 5) for i in range(20)])
    _belief(conn, "acute-chronic-workload-ratio.md")
    first = rob_model.refresh(conn)
    before = _rows(conn)
    stamp = conn.execute("SELECT MAX(updated_at) FROM rob_parameters").fetchone()
    second = rob_model.refresh(conn)
    assert first["written"] >= 10 and second["written"] == 0
    assert _rows(conn) == before
    assert conn.execute("SELECT MAX(updated_at) FROM rob_parameters").fetchone() == stamp


def test_fake_citation_raises(conn) -> None:
    with pytest.raises(ValueError, match="not a vault note"):
        rob_model.validate_citation("made-up-note.md", 1.0, 0.1)
    with pytest.raises(ValueError):
        rob_model.validate_citation(rob_model.NO_PRIOR, 1.0, None)
    bad = _belief(conn, "made-up-note.md")
    result = rob_model.refresh(conn)
    assert any(s["key"] == f"belief.{bad}" for s in result["skipped"])
    assert conn.execute(
        "SELECT COUNT(*) FROM rob_parameters WHERE key LIKE 'belief.%'"
    ).fetchone() == (0,)


def test_no_evidence_parameter_shows_prior(conn) -> None:
    rob_model.refresh(conn)
    row = conn.execute(
        "SELECT prior_mean, post_mean, n_evidence, status, prior_source "
        "FROM rob_parameters WHERE key = 'cond_acwr_forbid_legs'"
    ).fetchone()
    assert row == (
        metrics.COND_ACWR_FORBID_LEGS, metrics.COND_ACWR_FORBID_LEGS, 0,
        "prior only", "acute-chronic-workload-ratio.md",
    )  # fmt: skip
    nulls = conn.execute(
        "SELECT COUNT(*) FROM rob_parameters WHERE prior_source = ? AND post_mean IS NOT NULL",
        [rob_model.NO_PRIOR],
    ).fetchone()
    assert nulls == (0,)


def test_values_come_from_engine_tables(conn, seed) -> None:
    hrv = [48.0, 52.0, 50.0, 55.0, 47.0, 53.0, 51.0, 49.0]
    _hrv(conn, hrv)
    _belief(conn, "acute-chronic-workload-ratio.md")
    for i in range(6):
        seed.workout(date.today() - timedelta(days=3 * (i + 1)), "Synthetic Press", [(40.0 + i, 8)])
    rob_model.refresh(conn)
    get = lambda k: conn.execute(  # noqa: E731
        "SELECT post_mean, status FROM rob_parameters WHERE key = ?", [k]
    ).fetchone()
    assert get("noise_hrv") == (swc(hrv), "established")
    assert get("noise_rhr") == (None, "prior only")
    assert conn.execute(
        "SELECT COUNT(*) FROM rob_parameters WHERE key = 'lift_noise.synthetic-press'"
    ).fetchone() == (1,)
    belief = conn.execute(
        "SELECT post_mean, n_evidence, domain FROM rob_parameters WHERE key LIKE 'belief.%'"
    ).fetchone()
    assert belief == (0.8, 2, "sleep")
    # Nothing without a source table row: no belief or lift rows on an empty DB.
    conn.execute("DELETE FROM rob_parameters")
    conn.execute("DELETE FROM research_beliefs")
    conn.execute("DELETE FROM workout_sets")
    rob_model.refresh(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM rob_parameters WHERE key LIKE 'belief.%' OR key LIKE 'lift_noise.%'"
    ).fetchone() == (0,)


def test_route_groups_by_domain_and_get_does_not_write(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def _write():
        yield conn

    monkeypatch.setattr(model_router, "get_read_conn", conn.cursor)
    monkeypatch.setattr(model_router, "write_ctx", _write)
    app = FastAPI()
    app.include_router(model_router.router, prefix="/api")
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    assert client.get("/api/model").json() == {"count": 0, "domains": {}}
    assert conn.execute("SELECT COUNT(*) FROM rob_parameters").fetchone() == (0,)

    assert client.post("/api/model/refresh").json()["written"] >= 10
    body = client.get("/api/model").json()
    assert body["count"] >= 10
    assert {"training", "sleep", "recovery"} <= set(body["domains"])
    p = body["domains"]["training"][0]
    assert {"label", "literature", "rob", "how_sure", "evidence", "changes"} <= set(p)
