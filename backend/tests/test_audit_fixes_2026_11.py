"""Guards for the data-loss and false-finding defects in the 2026-11-01 audit."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import duckdb
import pytest
import yaml

from shc import lab, selflab
from shc.ai.workout_planner import GateViolation, validate_plan
from shc.db import schema
from shc.ingest import clinical_profile, hevy
from shc.stats.scorecard import scorecard
from shc.training import loadable
from shc.training.mesocycle import volume_targets, weekly_budget_block
from shc.training.prescriptor import _advance
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


def test_budget_block_counts_this_weeks_direct_sets_including_bodyweight(conn):
    monday = date(2026, 11, 2)
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES ('w', 'hevy', ?, 'strength', 'h')",
        [datetime(2026, 11, 3)],
    )
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role) "
        "VALUES ('Test Dip', 'chest', 'primary')"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, "
            "is_warmup, content_hash) VALUES (?, 'w', ?, 'Test Dip', 0, 10, FALSE, ?)",
            [f"s{i}", i, f"c{i}"],
        )
    lines = weekly_budget_block(conn, monday)
    assert "- chest: 3/10 done, 7 left" in lines
    assert "- quads: 0/8 done, 8 left" in lines


def test_budget_tiers_hold_abs_and_raise_back_after_migration(conn):
    targets = volume_targets(conn)
    assert targets["abs"].tier == "maintain" and targets["abs"].mv == 4
    assert all(targets[m].mv == 3 for m in ("lats", "mid_back", "hamstrings"))
    emphasis = {r[0] for r in conn.execute("SELECT muscle FROM muscle_emphasis").fetchall()}
    assert "abs" not in emphasis


def _gate_plan(exercise: dict, intensity: str = "low") -> dict:
    return {
        "generated_at": "2026-11-01T08:00:00",
        "source": "t",
        "readiness_tier": "yellow",
        "readiness_summary": "s",
        "recommendation": {"intensity": intensity, "focus": "f", "rationale": "r", "target_rpe": 6},
        "warmup": [],
        "blocks": [{"label": "b", "exercises": [{"rest_seconds": 60, "notes": "n", **exercise}]}],
        "cooldown": "c",
        "clinical_notes": ["c"],
        "vault_insights": ["i"],
    }


def _state(**gates: object) -> dict:
    base = {
        "max_intensity": "low",
        "forbid_muscle_groups": [],
        "forbid_muscles": [],
        "deload_required": False,
        "reasons": [],
    }
    return {"gates": {**base, **gates}}


@pytest.mark.parametrize(
    "bad",
    [
        {"reps": "10"},
        {"sets": 0, "reps": "10"},
        {"sets": "three", "reps": "10"},
        {"sets": 3, "reps": "AMRAP"},
        {"sets": 3, "reps": "10", "weight_lbs": -100},
        {"sets": 3, "reps": "10", "rpe_target": "hard"},
    ],
)
def test_malformed_exercise_values_are_rejected_with_a_message(bad):
    with pytest.raises(ValueError):
        validate_plan(_gate_plan({"name": "Face Pull", **bad}))


def test_impossible_per_hand_load_is_rejected():
    with pytest.raises(GateViolation, match="one-hand"):
        validate_plan(
            _gate_plan({"name": "Lunge (Dumbbell)", "sets": 3, "reps": "10", "weight_lbs": 200})
        )


def test_z2_only_day_rejects_lifting_unless_overridden():
    lift = {"name": "Face Pull", "sets": 3, "reps": "10", "weight_lbs": 50, "rpe_target": 6}
    with pytest.raises(GateViolation, match="Z2 only"):
        validate_plan(_gate_plan(lift), state=_state(z2_only=True))
    walk = {"name": "Walking", "sets": 1, "reps": "30 min", "weight_lbs": None, "rpe_target": 4}
    assert validate_plan(_gate_plan(walk), state=_state(z2_only=True))
    assert validate_plan(
        _gate_plan(lift), state=_state(z2_only=True), override_reason="Rob confirmed he is well"
    )


def test_deload_effort_cap_applies_at_null_weight():
    hard = {"name": "Face Pull", "sets": 3, "reps": "10", "weight_lbs": None, "rpe_target": 10}
    with pytest.raises(GateViolation, match="effort cap"):
        validate_plan(
            _gate_plan(hard), state=_state(deload_required=True, max_intensity="moderate")
        )


def test_high_rep_set_is_not_held_to_a_twelve_rep_load():
    # 15 lb x 25 at RPE 9 against the e1RM its own 12-rep cap produces (21 lb).
    plan = _gate_plan(
        {
            "name": "Lateral Raise (Dumbbell)",
            "sets": 2,
            "reps": "25",
            "weight_lbs": 15,
            "rpe_target": 9,
        },
        intensity="high",
    )
    state = _state(max_intensity="high")
    assert validate_plan(
        plan, state=state, e1rm_ceilings={"Lateral Raise (Dumbbell)": 21 / 2.20462}
    )


def test_scorecard_on_an_empty_database_says_not_measured(conn):
    card = scorecard(conn, today=date(2026, 11, 1))
    assert {m["status"] for m in card["metrics"]} == {"not measured"}
    assert len(card["metrics"]) == 6


class _Stack:
    """A weight stack that only moves in 15 lb jumps."""

    def snap_up(self, _name: str, lb: float) -> float:
        return 15.0 * math.ceil(lb / 15.0)

    def snap_down(self, _name: str, lb: float) -> float:
        return 15.0 * math.floor(lb / 15.0)


def test_lighter_notch_passes_when_the_next_one_is_over_the_ceiling(conn, monkeypatch):
    monkeypatch.setattr(loadable, "build_grids", lambda _conn: _Stack())
    # e1RM 210 lb at 12 reps: an RPE 8 set wants about 143 lb, and the stack offers 135 or 150.
    state = _state(max_intensity="moderate")
    e1rm = {"Face Pull": 210 / 2.20462}
    plan = _gate_plan(
        {"name": "Face Pull", "sets": 2, "reps": "12", "weight_lbs": 120, "rpe_target": 8},
        intensity="moderate",
    )
    with pytest.raises(GateViolation, match="implies RPE"):
        validate_plan(plan, state=state, e1rm_ceilings=e1rm, conn=conn)  # 135 is still legal
    plan["blocks"][0]["exercises"][0]["weight_lbs"] = 135
    assert validate_plan(plan, state=state, e1rm_ceilings=e1rm, conn=conn)


def test_next_load_uses_the_ceiling_tolerance_and_reaches_the_rep_window():
    action, weight, reps, _ = _advance("Curl", 135, 11, 8.0, 8, 12, _Stack(), lambda _reps: 133.0)
    assert (action, weight, reps) == ("reduce_ceiling", 135, 11)

    action, weight, reps, _ = _advance("Raise", 15, 8, 8.0, 12, 20, _Stack(), lambda _reps: None)
    assert (action, weight, reps) == ("add_rep", 15, 12)

    action, weight, reps, _ = _advance("Raise", 30, 8, 8.0, 12, 20, _Stack(), lambda _reps: 20.0)
    assert (action, weight, reps) == ("reduce_ceiling", 15, 12)
