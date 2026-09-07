"""Guards for the engine's own report card.

The point of this module is to make a claim about the engine, so the tests are
about refusing to make that claim when the data cannot support it — and about
getting the sign right when it can, since `bias` is the one field a reader will
act on.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from shc.stats.engine_report import prescription_calibration, readiness_validity, report_card

_TODAY = date.today()


def _plan(conn, day: date, exercises: list[tuple[str, float]]) -> None:
    payload = {"blocks": [{"label": "A", "exercises": [{"name": n, "rpe_target": t} for n, t in exercises]}]}
    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source, created_at) VALUES (?,?,'test',now())",
        [day, json.dumps(payload)],
    )


def _session(conn, day: date, sets: list[tuple[str, float, float]]) -> None:
    wid = f"w{day}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) VALUES (?,'hevy',?,'strength',?)",
        [wid, datetime.combine(day, datetime.min.time()), f"h{day}"],
    )
    for i, (ex, rpe, _w) in enumerate(sets):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, rpe, is_warmup, content_hash) "
            "VALUES (?,?,?,?,?,?,?,FALSE,?)",
            [f"{wid}s{i}", wid, i, ex, 50.0, 10, rpe, f"c{wid}{i}"],
        )


def test_calibration_refuses_a_verdict_on_thin_data(conn):
    _plan(conn, _TODAY, [("Bench Press", 8.0)])
    _session(conn, _TODAY, [("Bench Press", 8.0, 50.0)])
    assert prescription_calibration(conn)["verdict"] == "insufficient"


def test_calibration_detects_a_systematic_overshoot(conn):
    """Every session a full point harder than programmed must read as biased."""
    for i in range(20):
        d = _TODAY - timedelta(days=i + 1)
        _plan(conn, d, [("Bench Press", 7.0)])
        _session(conn, d, [("Bench Press", 8.0, 50.0)])
    out = prescription_calibration(conn)
    assert out["n_matched"] == 20
    assert out["bias_rpe"] == pytest.approx(1.0)
    assert out["verdict"] == "biased"
    assert out["harder_than_programmed_pct"] == 100.0


def test_calibration_calls_a_matching_engine_calibrated(conn):
    for i in range(20):
        d = _TODAY - timedelta(days=i + 1)
        _plan(conn, d, [("Bench Press", 8.0)])
        _session(conn, d, [("Bench Press", 8.0 + (0.2 if i % 2 else -0.2), 50.0)])
    out = prescription_calibration(conn)
    assert out["verdict"] == "calibrated"
    assert out["within_target_pct"] == 100.0


def test_calibration_reads_rpe_target_not_target_rpe(conn):
    """The key name is the whole feature. A wrong guess yields a silent zero."""
    for i in range(20):
        d = _TODAY - timedelta(days=i + 1)
        conn.execute(
            "INSERT INTO workout_plans (date, plan_json, source, created_at) VALUES (?,?,'test',now())",
            [d, json.dumps({"blocks": [{"exercises": [{"name": "Bench Press", "target_rpe": 8.0}]}]})],
        )
        _session(conn, d, [("Bench Press", 8.0, 50.0)])
    # Written under the WRONG key, so nothing should be picked up at all.
    assert prescription_calibration(conn)["n_prescribed"] == 0


def _readiness_day(conn, day: date, score: float, n_sets: int, rpe: float) -> None:
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, content_hash) VALUES (?,'whoop',?,?,?,?)",
        [f"r{day}", day, score, 100.0, f"rh{day}"],
    )
    wid = f"wr{day}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) VALUES (?,'hevy',?,'strength',?)",
        [wid, datetime.combine(day, datetime.min.time()), f"hr{day}"],
    )
    for i in range(n_sets):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, rpe, is_warmup, content_hash) "
            "VALUES (?,?,?,'Bench Press',50.0,10,?,FALSE,?)",
            [f"{wid}s{i}", wid, i, rpe, f"c{wid}{i}"],
        )


def test_validity_finds_a_relationship_when_one_exists(conn):
    """Readiness driving set count must be detected, or the metric is useless."""
    for i in range(24):
        d = _TODAY - timedelta(days=i + 1)
        score = 40 + i * 2
        _readiness_day(conn, d, score, 8 + i // 3, 7.5)
    out = readiness_validity(conn)
    assert out["n"] == 24
    assert out["correlations"]["working_sets"]["excludes_zero"] is True
    assert out["informative"] is True


def test_validity_reports_null_without_pretending_it_is_proof(conn):
    for i in range(24):
        d = _TODAY - timedelta(days=i + 1)
        _readiness_day(conn, d, 40 + (i % 5) * 10, 10, 7.5)
    out = readiness_validity(conn)
    assert out["informative"] is False
    assert out["verdict"] == "no detectable relationship"
    assert "not proof" in out["caveat"]


def test_report_card_summarises_both_axes(conn):
    for i in range(20):
        d = _TODAY - timedelta(days=i + 1)
        _plan(conn, d, [("Bench Press", 8.0)])
        _readiness_day(conn, d, 40 + (i % 5) * 10, 10, 8.0)
    out = report_card(conn)
    assert "calibration" in out and "predictive_validity" in out
    assert isinstance(out["summary"], str) and out["summary"]


# ── component-level validity ────────────────────────────────────────────────


def _night(conn, day, hours: float) -> None:
    from datetime import datetime as _dt

    ts_in = _dt.combine(day, _dt.min.time()).replace(hour=23)
    conn.execute(
        "INSERT INTO sleep (id, source, night_date, ts_in, ts_out, is_nap, content_hash) "
        "VALUES (?,'whoop',?,?,?,FALSE,?)",
        [f"s{day}", day, ts_in, ts_in + timedelta(hours=hours), f"sh{day}"],
    )


def test_component_validity_isolates_the_input_that_predicts(conn):
    """A composite null cannot say WHICH input is dead. This must."""
    from shc.stats.engine_report import component_validity

    for i in range(26):
        d = _TODAY - timedelta(days=i + 1)
        # sleep drives set count; hrv/rhr are flat noise
        _readiness_day(conn, d, 60.0, 8 + i // 3, 7.5)
        _night(conn, d, 6.0 + i * 0.1)
    out = component_validity(conn)
    assert out["n"] >= 20
    assert "sleep" in out["components_carrying_signal"]
    assert out["components"]["sleep"]["predicts_anything"] is True


def test_component_validity_totals_the_weight_sitting_on_silent_inputs(conn):
    """The headline number: how much of the composite rests on nothing."""
    from shc.stats.engine_report import component_validity

    for i in range(26):
        d = _TODAY - timedelta(days=i + 1)
        _readiness_day(conn, d, 60.0, 10, 7.5)   # nothing varies with anything
        _night(conn, d, 8.0)
    out = component_validity(conn)
    assert out["components_carrying_signal"] == []
    assert out["weight_on_silent_components"] == pytest.approx(0.90)


def test_component_validity_refuses_on_thin_data(conn):
    from shc.stats.engine_report import component_validity

    assert component_validity(conn)["verdict"] == "insufficient"


def test_component_validity_states_that_it_does_not_decide(conn):
    """Guard the boundary: this reports, a weight change is a gate change."""
    from shc.stats.engine_report import component_validity

    for i in range(26):
        d = _TODAY - timedelta(days=i + 1)
        _readiness_day(conn, d, 60.0, 10, 7.5)
        _night(conn, d, 8.0)
    assert "does not decide" in component_validity(conn)["note"]
