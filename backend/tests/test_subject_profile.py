from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

from shc.api.routers.subject import build_subject_profile
from shc import selflab


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


# ── suggest_experiments ──────────────────────────────────────────────────────


def test_suggest_inconclusive_manipulable_finding(conn: duckdb.DuckDBPyConnection):
    """An inconclusive finding with a controllable-behavior question → candidate returned."""
    conn.execute(
        "INSERT INTO lab_findings (id, question_id, run_at, n, verdict, summary) "
        "VALUES ('f1', 'sleep_short_hrv_drop', now(), 15, 'inconclusive', 'test')"
    )
    suggestions = selflab.suggest_experiments(conn)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["slug"] == "suggest-sleep-timing-hrv"
    assert s["from_question_id"] == "sleep_short_hrv_drop"
    assert s["lab_verdict"] == "inconclusive"
    assert "hypothesis" in s
    assert "condition_a" in s and "condition_b" in s


def test_suggest_non_manipulable_finding_excluded(conn: duckdb.DuckDBPyConnection):
    """A non-manipulable question (skin_temp_illness_alarm) → no candidate."""
    conn.execute(
        "INSERT INTO lab_findings (id, question_id, run_at, n, verdict, summary) "
        "VALUES ('f2', 'skin_temp_illness_alarm', now(), 10, 'inconclusive', 'test')"
    )
    suggestions = selflab.suggest_experiments(conn)
    assert suggestions == []


def test_suggest_suppresses_registered_slug(conn: duckdb.DuckDBPyConnection):
    """If a study with the candidate slug already exists, it is suppressed."""
    conn.execute(
        "INSERT INTO lab_findings (id, question_id, run_at, n, verdict, summary) "
        "VALUES ('f3', 'rest_day_hrv_rebound', now(), 12, 'insufficient', 'test')"
    )
    # Pre-register a study with the candidate slug
    selflab.preregister(
        conn,
        slug="suggest-full-rest-day-hrv",
        hypothesis="test",
        manipulated="rest",
        condition_a="train",
        condition_b="rest",
        outcome_metric="hrv_next_morning",
        min_effect=1.0,
    )
    suggestions = selflab.suggest_experiments(conn)
    slugs = [s["slug"] for s in suggestions]
    assert "suggest-full-rest-day-hrv" not in slugs


def test_suggest_deduplicates_same_slug(conn: duckdb.DuckDBPyConnection):
    """Two question IDs that map to the same slug produce only one candidate."""
    for fid, qid in [("f4", "sleep_short_hrv_drop"), ("f5", "long_sleep_hrv_lift")]:
        conn.execute(
            "INSERT INTO lab_findings (id, question_id, run_at, n, verdict, summary) "
            "VALUES (?, ?, now(), 10, 'inconclusive', 'test')",
            [fid, qid],
        )
    suggestions = selflab.suggest_experiments(conn)
    slugs = [s["slug"] for s in suggestions]
    assert slugs.count("suggest-sleep-timing-hrv") == 1
