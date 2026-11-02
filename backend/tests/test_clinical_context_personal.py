from __future__ import annotations

import duckdb
import pytest

from shc.ai import briefing


@pytest.fixture
def empty_conn():
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE medications (name TEXT, dose TEXT, frequency TEXT, started DATE,"
        " stopped DATE, valid_to TIMESTAMP)"
    )
    conn.execute("CREATE TABLE conditions (name TEXT, status TEXT, onset DATE, valid_to TIMESTAMP)")
    conn.execute(
        "CREATE TABLE labs (name TEXT, value DOUBLE, unit TEXT, ref_low DOUBLE,"
        " ref_high DOUBLE, collected_at TIMESTAMP)"
    )
    yield conn
    conn.close()


def test_personal_context_reaches_clinical_block(empty_conn, monkeypatch) -> None:
    monkeypatch.setattr(briefing, "load_personal_context", lambda: "## Synthetic rule")
    assert "## Synthetic rule" in briefing.build_clinical_context(empty_conn)


def test_nothing_on_record_returns_empty(empty_conn, monkeypatch) -> None:
    monkeypatch.setattr(briefing, "load_personal_context", lambda: "")
    assert briefing.build_clinical_context(empty_conn) == ""
