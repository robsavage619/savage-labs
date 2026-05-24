from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from shc.ai.quality import (
    adherence_completion_trend,
    citation_validity_rate,
    rpe_calibration_error,
)
from shc.ai.workout_planner import CitationError, validate_plan

# ── fixtures ─────────────────────────────────────────────────────────────────

def _add_adherence(
    conn: duckdb.DuckDBPyConnection,
    day: date,
    *,
    completion_pct: float | None = None,
    actual: float | None = None,
    target: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO plan_adherence
            (date, plan_date, completion_pct, avg_rpe_actual, avg_rpe_target)
        VALUES (?, ?, ?, ?, ?)
        """,
        [day, day, completion_pct, actual, target],
    )


def _add_stored_plan(conn: duckdb.DuckDBPyConnection, day: date, vault_insights: list[str]) -> None:
    import json

    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source) VALUES (?, ?, ?)",
        [day, json.dumps({"vault_insights": vault_insights}), "test"],
    )


def _plan(*, vault_insights: list[str]) -> dict:
    return {
        "readiness_tier": "yellow",
        "recommendation": {
            "intensity": "low",
            "focus": "test",
            "rationale": "x",
            "estimated_duration_min": 40,
            "target_rpe": 6,
        },
        "warmup": [{"name": "Walking", "sets": 1, "reps": 5}],
        "blocks": [
            {
                "label": "A",
                "exercises": [
                    {"name": "Face Pull", "sets": 3, "reps": "8", "weight_lbs": 50,
                     "rpe_target": 6, "rest_seconds": 120},
                ],
            }
        ],
        "cooldown": "walk",
        "clinical_notes": ["propranolol PRN; asthma"],
        "vault_insights": vault_insights,
    }


# ── rpe_calibration_error ────────────────────────────────────────────────────

def test_rpe_calibration_error_mean_abs(conn: duckdb.DuckDBPyConnection) -> None:
    today = date.today()
    _add_adherence(conn, today - timedelta(days=1), actual=8.0, target=7.0)   # |+1|
    _add_adherence(conn, today - timedelta(days=2), actual=6.0, target=8.0)   # |−2|
    assert rpe_calibration_error(conn, days=14) == pytest.approx(1.5)


def test_rpe_calibration_error_none_when_empty(conn: duckdb.DuckDBPyConnection) -> None:
    assert rpe_calibration_error(conn, days=14) is None


def test_rpe_calibration_error_ignores_rows_outside_window(conn: duckdb.DuckDBPyConnection) -> None:
    today = date.today()
    _add_adherence(conn, today - timedelta(days=40), actual=10.0, target=1.0)  # out of 14d window
    assert rpe_calibration_error(conn, days=14) is None


# ── adherence_completion_trend ───────────────────────────────────────────────

def test_completion_trend_improving(conn: duckdb.DuckDBPyConnection) -> None:
    today = date.today()
    for i, pct in enumerate([50.0, 60.0, 90.0, 100.0]):
        _add_adherence(conn, today - timedelta(days=4 - i), completion_pct=pct)
    out = adherence_completion_trend(conn, days=30)
    assert out["n"] == 4
    assert out["latest"] == 100.0
    assert out["direction"] == "improving"


def test_completion_trend_empty(conn: duckdb.DuckDBPyConnection) -> None:
    out = adherence_completion_trend(conn, days=30)
    assert out == {"latest": None, "mean": None, "n": 0, "direction": "insufficient"}


# ── citation_validity_rate ───────────────────────────────────────────────────

def test_citation_validity_rate(conn: duckdb.DuckDBPyConnection) -> None:
    allowed = {"real-note.md", "another.md"}
    today = date.today()
    _add_stored_plan(conn, today - timedelta(days=1), ["grounded in `real-note.md`"])     # valid
    _add_stored_plan(conn, today - timedelta(days=2), ["cites `ghost.md` which is fake"])  # invalid
    _add_stored_plan(conn, today - timedelta(days=3), ["no citation at all"])              # invalid
    assert citation_validity_rate(conn, allowed, days=90) == pytest.approx(1 / 3, abs=1e-3)


def test_citation_validity_rate_none_when_vault_unavailable(conn: duckdb.DuckDBPyConnection) -> None:
    assert citation_validity_rate(conn, set(), days=90) is None


# ── validate_plan citation enforcement (property) ────────────────────────────

def test_citation_check_rejects_unknown_note() -> None:
    plan = _plan(vault_insights=["per `made-up-study.md` you should squat"])
    with pytest.raises(CitationError):
        validate_plan(plan, allowed_citations={"progressive-overload-strength.md"})


def test_citation_check_rejects_no_real_citation() -> None:
    plan = _plan(vault_insights=["(Gabbett, 2016) says ACWR matters"])
    with pytest.raises(CitationError):
        validate_plan(plan, allowed_citations={"progressive-overload-strength.md"})


def test_citation_check_passes_real_note() -> None:
    plan = _plan(vault_insights=["grounded in `progressive-overload-strength.md`"])
    assert validate_plan(plan, allowed_citations={"progressive-overload-strength.md"}) is True


def test_citation_check_skipped_when_not_requested() -> None:
    # Backwards-compat: omitting allowed_citations skips the check entirely.
    plan = _plan(vault_insights=["a", "b"])
    assert validate_plan(plan) is True
