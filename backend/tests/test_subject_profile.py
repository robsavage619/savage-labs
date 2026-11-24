from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

from shc.api.routers.subject import build_subject_profile


@pytest.fixture
def seeded_conn(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """Minimal data: one recovery row + one workout so enrolled_on is deterministic."""
    d = date(2024, 1, 15)
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) "
        "VALUES ('r1', 'whoop', ?, 70, 55, 58, 'r1')",
        [d],
    )
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES ('w1', 'hevy', ?, 'strength', 'w1')",
        [datetime.combine(d, datetime.min.time())],
    )
    return conn


def test_fitted_params_lte_total(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    pers = profile["personalization"]
    assert pers["fitted_params"] <= pers["total_params"]


def test_enrolled_on_matches_seeded_date(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    assert profile["enrolled_on"] == "2024-01-15"


def test_days_observed_positive(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    assert profile["days_observed"] is not None
    assert profile["days_observed"] > 0


def test_phenotype_is_list_of_strings(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    assert isinstance(profile["phenotype"], list)
    for tag in profile["phenotype"]:
        assert isinstance(tag, str) and len(tag) > 0


def test_muscle_coverage_sane(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    cov = profile["muscle_coverage"]
    assert cov["personalized"] <= cov["total"]
    assert cov["total"] >= 0


def test_engine_accuracy_structure(seeded_conn):
    profile = build_subject_profile(seeded_conn)
    acc = profile["engine_accuracy"]
    assert "current" in acc
    assert "history" in acc
    assert isinstance(acc["history"], list)
