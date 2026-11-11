from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc import research_team as rt

TODAY = date(2026, 6, 30)


def _seed_strain(conn, days: int = 40) -> None:
    for i in range(days):
        d = TODAY - timedelta(days=i)
        conn.execute(
            "INSERT INTO daily_cycle (id, date, strain, content_hash) VALUES (?, ?, ?, ?)",
            [f"c{i}", d, 5.0 + i % 7, f"k{i}"],
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO daily_cycle (id) VALUES ('x')",
        "UPDATE daily_cycle SET strain = 0",
        "WITH x AS (SELECT 1) DELETE FROM daily_cycle",
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE daily_cycle",
        "ATTACH 'other.duckdb' AS o",
        "SELECT * FROM daily_cycle; ATTACH 'x.duckdb'",
        "COPY daily_cycle TO 'out.csv'",
        "PRAGMA database_list",
        "SELECT * FROM pragma_database_list()",
        "SELECT * FROM read_csv('x.csv')",
        "SELECT * FROM 'x.parquet'",
        "SELECT * FROM glob('*')",
        "SELECT getenv('HOME')",
        "SELECT * FROM duckdb_settings()",
        "SELECT * FROM oauth_state",
        "SELECT * FROM nope_table",
        "",
        "-- comment first\nSELECT 1",
    ],
)
def test_guard_refuses(conn, sql: str) -> None:
    with pytest.raises(rt.SqlGuardError):
        rt.check_sql(conn, sql)


def test_guard_allows_plain_reads(conn) -> None:
    for sql in (
        "SELECT date, strain FROM daily_cycle",
        "WITH w AS (SELECT date, strain FROM daily_cycle) SELECT * FROM w WHERE strain > 3",
        "SELECT r.range FROM range(3) r",
        "SELECT 'please update me' AS s",
        "SELECT table_name, column_name FROM duckdb_columns() WHERE schema_name = 'main'",
    ):
        rt.check_sql(conn, sql)


@pytest.mark.parametrize(
    ("sql", "msg"),
    [
        ("SELECT date, strain, strain FROM daily_cycle", "two columns"),
        ("SELECT 'not a date', strain FROM daily_cycle", "date"),
        ("SELECT date, 'high' FROM daily_cycle", "numeric"),
        ("SELECT DATE '2026-06-01', strain FROM daily_cycle", "one row per date"),
        ("SELECT date, strain FROM daily_cycle LIMIT 3", "at least"),
        ("SELECT date + 400, strain FROM daily_cycle", "after today"),
    ],
)
def test_bad_measurement_shapes_are_refused(conn, sql: str, msg: str) -> None:
    _seed_strain(conn)
    with pytest.raises(rt.TeamError, match=msg):
        rt.propose_custom(
            conn, "strain_copy", "recovery", "Day strain, copied", "strain", "day", sql
        )
    assert rt.list_custom(conn) == []


def test_custom_feature_resolves_only_when_approved(conn) -> None:
    _seed_strain(conn)
    sql = "SELECT date, strain FROM daily_cycle"
    out = rt.propose_custom(
        conn, "strain_copy", "recovery", "Day strain, copied", "strain", "day", sql
    )
    assert out["status"] == "proposed" and out["days"] == 40
    name = "custom:strain_copy"
    assert not rt.known_custom(conn, name)
    with pytest.raises(ValueError):
        rt.custom_series(conn, name)
    with pytest.raises(rt.TeamError):
        rt.review_custom(conn, name, "approve", "self approval is not a review", author="recovery")
    rt.review_custom(conn, name, "approve", "Measures day strain as described.")
    assert rt.known_custom(conn, name)
    assert len(rt.custom_series(conn, name)) == 40
    assert [r["name"] for r in rt.custom_dictionary(conn)] == [name]
    with pytest.raises(rt.TeamError, match="already approved"):
        rt.propose_custom(
            conn, "strain_copy", "recovery", "Changed after approval", "x", "day", sql
        )

    rt.propose_custom(conn, "strain_two", "metabolic", "Day strain, again", "strain", "day", sql)
    rt.review_custom(conn, "strain_two", "reject", "Duplicates an existing feature.")
    assert not rt.known_custom(conn, "custom:strain_two")
    kinds = [
        r[0]
        for r in conn.execute("SELECT kind FROM research_notebook ORDER BY written_at").fetchall()
    ]
    assert kinds.count("measurement") == 2 and kinds.count("review") == 2


def test_agenda_round_trips_and_notes_the_change(conn) -> None:
    lead = {
        "lead": "Biceps sets vs arm girth",
        "why": "Emphasis muscle",
        "priority": 4,
        "status": "open",
    }
    first = rt.set_agenda(
        conn, "hypertrophy", {"interests": "Volume", "open_leads": [lead]}, today=TODAY
    )
    assert first["open_leads"][0]["opened"] == TODAY.isoformat()
    later = TODAY + timedelta(days=7)
    second = rt.set_agenda(
        conn,
        "hypertrophy",
        {"interests": "Volume", "open_leads": [{**lead, "status": "chasing", "priority": 5}]},
        today=later,
    )
    assert second["open_leads"][0]["opened"] == TODAY.isoformat()
    stored = rt.get_agenda(conn, "hypertrophy")
    assert stored is not None and stored["open_leads"][0]["status"] == "chasing"
    assert "open → chasing: Biceps sets vs arm girth" in second["changes"]
    notes = conn.execute(
        "SELECT author, body FROM research_notebook WHERE kind = 'agenda' ORDER BY written_at"
    ).fetchall()
    assert len(notes) == 2 and notes[0][0] == "hypertrophy" and "Priority 4 → 5" in notes[1][1]
    board = {r["researcher"]: r for r in rt.team(conn)}
    assert set(board) == set(rt.RESEARCHERS)
    assert board["hypertrophy"]["last_activity"]["kind"] == "agenda"
    assert board["recovery"]["agenda"] is None and board["recovery"]["last_activity"] is None


@pytest.mark.parametrize(
    "agenda",
    [
        {"open_leads": [{"lead": "x", "why": "y", "priority": 6}]},
        {"open_leads": [{"lead": "x", "why": "y", "priority": 3, "status": "maybe"}]},
        {"open_leads": [{"lead": "x", "why": "y", "priority": True}]},
        {"open_leads": [{"lead": "x", "priority": 3}]},
        {"open_leads": [{"lead": "x", "why": "y", "priority": 3, "extra": 1}]},
        {"open_leads": "not a list"},
        {"mood": "great"},
    ],
)
def test_malformed_agenda_is_refused(conn, agenda: dict) -> None:
    with pytest.raises(rt.TeamError):
        rt.set_agenda(conn, "recovery", agenda)
    assert rt.get_agenda(conn, "recovery") is None


def test_unknown_researcher_is_refused(conn) -> None:
    with pytest.raises(rt.TeamError):
        rt.set_agenda(conn, "analyst", {})


def test_query_caps_rows_and_times_out(conn) -> None:
    out = rt.run_query(conn, "SELECT range AS n FROM range(5000)")
    assert out["columns"] == ["n"] and out["row_count"] == rt.EXPLORE_ROW_CAP and out["truncated"]
    assert (
        rt.run_query(conn, "SELECT range FROM range(5000)", cap=10_000)["row_count"]
        == rt.EXPLORE_ROW_CAP
    )
    small = rt.run_query(conn, "SELECT DATE '2026-01-01' AS d, 1.5 AS v")
    assert small["rows"] == [["2026-01-01", 1.5]] and not small["truncated"]
    with pytest.raises(rt.SqlGuardError, match="stopped"):
        rt.run_query(conn, "SELECT count(*) FROM range(100000000000)", timeout_s=0.2)


def test_exploration_is_a_notebook_entry_only(conn) -> None:
    nid = rt.record_exploration(
        conn,
        "conditioning",
        "Court minutes by weekday",
        "pickleball_min",
        "weekend mean 90 min",
        "court load",
        "opens",
    )
    row = conn.execute(
        "SELECT kind, author, body FROM research_notebook WHERE id = ?", [nid]
    ).fetchone()
    assert (
        row[0] == "exploration" and row[1] == "conditioning" and "Opens lead: court load" in row[2]
    )
    assert conn.execute("SELECT count(*) FROM research_beliefs").fetchone()[0] == 0
    with pytest.raises(rt.TeamError):
        rt.record_exploration(conn, "conditioning", "t", "x", "y", "", "closes")


def test_approved_custom_feature_flows_through_research(conn) -> None:
    # Self-contained: importing helpers from another test module only works
    # when `tests` happens to be importable, which the pre-push run is not.
    import math
    import random

    from shc import research

    r_today = date(2026, 6, 30)
    rng = random.Random(3)
    start = r_today - timedelta(days=200)
    for i in range(201):
        d = start + timedelta(days=i)
        conn.execute(
            "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES (?, 'whoop', ?, 60, ?, 50, ?)",
            [f"r{i}", d, math.exp(math.log(100) + rng.gauss(0, 0.18)), f"h{i}"],
        )
        conn.execute(
            "INSERT INTO daily_cycle (id, date, strain, content_hash) VALUES (?, ?, ?, ?)",
            [f"c{i}", d, rng.uniform(4, 18), f"k{i}"],
        )
    spec_base = {
        "exposure": {"feature": "strain", "a": {"max": 10}, "b": {"min": 14}},
        "outcome": "lnhrv_dev_pct",
        "lag": 1,
        "unit": "day",
        "expected_sign": "-",
        "min_effect": 3,
    }
    rt.propose_custom(
        conn,
        "strain_copy",
        "recovery",
        "Day strain, copied",
        "strain",
        "day",
        "SELECT date, strain FROM daily_cycle",
    )
    rt.review_custom(conn, "strain_copy", "approve", "Measures day strain as described.")
    assert research.known_feature(conn, "custom:strain_copy")
    spec = {**spec_base, "exposure": {**spec_base["exposure"], "feature": "custom:strain_copy"}}
    research.validate_spec(conn, spec)
    assert (
        research.estimate(conn, spec, today=r_today)["effect"]
        == research.estimate(conn, spec_base, today=r_today)["effect"]
    )
    assert any(f["name"] == "custom:strain_copy" for f in research.dictionary(conn))


def test_custom_outcome_carries_its_declared_goal_weight(conn) -> None:
    from shc import research

    _seed_strain(conn)
    # Proposed by the recovery specialist, but it measures muscle.
    rt.propose_custom(
        conn,
        "copy_muscle",
        "recovery",
        "Day strain, copied",
        "strain",
        "day",
        "SELECT date, strain FROM daily_cycle",
        goal="muscle",
    )
    rt.propose_custom(
        conn,
        "copy_default",
        "metabolic",
        "Day strain, copied",
        "strain",
        "day",
        "SELECT date, strain FROM daily_cycle",
    )
    assert research.goal_of("custom:copy_muscle", conn) == "muscle"
    assert research.goal_of("custom:copy_default", conn) == "body"
    with pytest.raises(rt.TeamError, match="goal"):
        rt.propose_custom(
            conn,
            "bad_goal",
            "recovery",
            "Day strain, copied",
            "strain",
            "day",
            "SELECT date, strain FROM daily_cycle",
            goal="vibes",
        )
