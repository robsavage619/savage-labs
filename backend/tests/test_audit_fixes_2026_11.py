"""Guards for the data-loss and false-finding defects in the 2026-11-01 audit."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pytest
import yaml

from shc import lab, selflab
from shc.db import schema
from shc.ingest import clinical_profile, hevy
from shc.training.self_learning import accuracy_baseline


def _study(conn, direction: str, design: str = "randomized_alternating") -> str:
    return selflab.preregister(
        conn,
        slug=f"s-{direction}-{design}",
        hypothesis="h",
        manipulated="m",
        condition_a="a",
        condition_b="b",
        outcome_metric="hrv_next_morning",
        min_effect=1.0,
        outcome_direction=direction,
        design=design,
    )


def _fill(conn, exp_id: str, a: list[float], b: list[float]) -> None:
    day = date(2025, 1, 1)
    for arm, values in (("A", a), ("B", b)):
        for value in values:
            conn.execute(
                "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, outcome_value) "
                "VALUES (?, ?, ?, TRUE, ?)",
                [exp_id, day.isoformat(), arm, value],
            )
            day += timedelta(days=1)


LOW = [50.0, 51.0, 49.0, 50.5, 49.5, 50.0, 51.5, 48.5]
HIGH = [v + 20.0 for v in LOW]


def test_clear_effect_against_the_hypothesis_never_confirms(conn):
    exp_id = _study(conn, "lower_better")
    _fill(conn, exp_id, LOW, HIGH)
    result = selflab.score(conn, exp_id)
    assert result["effect"] > 0
    assert result["verdict"] == "INCONCLUSIVE"


def test_effect_in_the_hypothesized_direction_still_confirms(conn):
    exp_id = _study(conn, "higher_better")
    _fill(conn, exp_id, LOW, HIGH)
    assert selflab.score(conn, exp_id)["verdict"] == "CONFIRMED"
    assert selflab.active_priors(conn)


def test_observational_confirmation_emits_no_causal_prior(conn):
    exp_id = _study(conn, "higher_better", design="observational")
    _fill(conn, exp_id, LOW, HIGH)
    assert selflab.score(conn, exp_id)["verdict"] == "CONFIRMED"
    assert selflab.active_priors(conn) == []


def test_deleting_a_graded_workout_removes_it_and_its_dependents(conn):
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES ('w', 'hevy', ?, 'strength', 'h')",
        [datetime(2026, 1, 5)],
    )
    conn.execute(
        "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, is_warmup, "
        "content_hash) VALUES ('s', 'w', 0, 'Curl', 20, 10, FALSE, 'c')"
    )
    conn.execute(
        "INSERT INTO plan_adherence (date, plan_date, workout_id) "
        "VALUES ('2026-01-05', '2026-01-05', 'w')"
    )
    conn.execute("INSERT INTO workout_retrospectives (workout_id, summary) VALUES ('w', 'x')")

    hevy._delete_workout(conn, "w")

    for table, column in (
        ("workouts", "id"),
        ("workout_sets", "workout_id"),
        ("plan_adherence", "workout_id"),
        ("workout_retrospectives", "workout_id"),
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = 'w'").fetchone()[0] == 0


def test_failed_migration_rolls_back_and_retries_cleanly(tmp_path, monkeypatch):
    bad = tmp_path / "0001_bad.sql"
    bad.write_text(
        "CREATE TABLE t1 (a INT); INSERT INTO t1 VALUES (1); INSERT INTO nosuch VALUES (1);"
    )
    monkeypatch.setattr(schema, "_migration_files", lambda: [bad])
    c = duckdb.connect(":memory:")

    with pytest.raises(duckdb.Error):
        schema._apply_migrations(c)
    assert (
        c.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 't1'"
        ).fetchone()[0]
        == 0
    )

    bad.write_text("CREATE TABLE t1 (a INT);")
    schema._apply_migrations(c)
    assert c.execute("SELECT version FROM schema_version").fetchall() == [(1,)]


def test_malformed_clinical_yaml_leaves_existing_labs_intact(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "get_read_conn", lambda: conn.cursor())
    good = {"labs": [{"name": "A", "value": 1, "collected_at": "2026-01-01"}]}
    path = tmp_path / "p.yml"
    path.write_text(yaml.safe_dump(good))
    clinical_profile.ingest_clinical_profile(path)
    before = conn.execute("SELECT COUNT(*) FROM labs").fetchone()[0]

    path.write_text(yaml.safe_dump({"labs": [{"value": 2}]}))
    with pytest.raises(KeyError):
        clinical_profile.ingest_clinical_profile(path)

    assert before > 0
    assert conn.execute("SELECT COUNT(*) FROM labs").fetchone()[0] == before


def _rhr_question() -> dict:
    return {"id": "rhr_trend_hrv_drop", "window_days": 200, "min_n": 3, "threshold": 0.4}


def test_rhr_hit_rate_equal_to_other_days_is_not_confirmed(conn):
    start = date.today() - timedelta(days=120)
    for i in range(120):
        conn.execute(
            "INSERT INTO recovery (id, source, date, hrv, rhr, content_hash) VALUES (?, 'test', ?, ?, ?, ?)",
            # HRV dips every few days regardless of RHR, as it does in real data.
            [
                f"r{i}",
                (start + timedelta(days=i)).isoformat(),
                60.0 - (i % 3) * 5,
                50 + (i // 14) % 2 * 6,
                f"h{i}",
            ],
        )
    finding = lab._run_rhr_trend_hrv_drop(conn, _rhr_question())
    assert finding.effect_size is not None and finding.effect_size >= 0.4
    assert finding.verdict == "inconclusive"
    assert "other days" in finding.summary


def test_backup_is_openable_and_prunes_old_copies(tmp_path):
    db = tmp_path / "shc.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE schema_version (version INT); INSERT INTO schema_version VALUES (1)")
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    for day in range(1, 10):
        (dest_dir / f"shc-2020-01-0{day}.duckdb").touch()

    dest = schema.backup_database(c, dest_dir, keep=3)
    c.close()

    check = duckdb.connect(str(dest), read_only=True)
    assert check.execute("SELECT version FROM schema_version").fetchone() == (1,)
    check.close()
    assert len(list(dest_dir.glob("shc-*.duckdb"))) == 3
    assert dest.exists()


def test_accuracy_baseline_exposes_a_call_with_no_skill(conn):
    # Calls are unrelated to outcomes, so logged accuracy can't beat shuffled by much.
    start = date(2026, 1, 5)
    for i in range(60):
        conn.execute(
            "INSERT INTO muscle_prescription_log "
            "(week_start, muscle, action, target_sets, correct, outcome_perf) "
            "VALUES (?, 'm', ?, 10, TRUE, ?)",
            [
                (start + timedelta(weeks=i)).isoformat(),
                "hold" if i % 2 else "add",
                4 if i % 3 else 2,
            ],
        )
    baseline = accuracy_baseline(conn)
    assert baseline is not None and baseline["n"] == 60
    assert abs(baseline["logged"] - baseline["shuffled"]) < 0.1
    assert baseline["always_hold"] == pytest.approx(40 / 60, abs=0.001)
