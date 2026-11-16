"""Cut phase: volume tops out at MAV, and the planner prompt follows the stored phase."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from shc.ai.workout_planner import _bodyweight_rate_pct_wk, _cut_tracking_lines, _goal_lines
from shc.training.autoregulation import _decide, load_training_phase


def _d(current: float, perf: int, phase: str, emphasis: bool = False):
    # chest-like landmarks MEV 10 / MAV 16 / MRV 22; confidence clears the add gate.
    return _decide(
        "chest", current, 10, 16, 22, perf, 0.0, None,
        emphasis=emphasis, confidence=0.6, scored_weeks=4, phase=phase,
    )  # fmt: skip


def test_cut_holds_at_mav_where_build_keeps_adding():
    assert _d(16, perf=5, phase="build").target_sets == 17
    cut = _d(16, perf=5, phase="cut")
    assert cut.target_sets == 16
    assert "MAV (cut phase)" in cut.reason


def test_cut_trims_volume_already_above_mav():
    rx = _d(20, perf=5, phase="cut")
    assert rx.action == "cut"
    assert rx.target_sets == 16


def test_cut_still_lets_emphasis_ramp_below_mav():
    rx = _d(12, perf=5, phase="cut", emphasis=True)
    assert rx.target_sets == 14


def _set_phase(conn: duckdb.DuckDBPyConnection, value: str) -> None:
    conn.execute("DELETE FROM athlete_profile WHERE key = 'training_phase'")
    conn.execute("INSERT INTO athlete_profile (key, value) VALUES ('training_phase', ?)", [value])


def test_phase_defaults_to_build_and_rejects_unknown_values(conn):
    assert load_training_phase(conn) == "build"
    _set_phase(conn, " Cut ")
    assert load_training_phase(conn) == "cut"
    _set_phase(conn, "bulk")
    assert load_training_phase(conn) == "build"


def test_goal_lines_follow_phase_and_live_emphasis(conn):
    conn.execute("DELETE FROM muscle_emphasis")
    conn.execute(
        "INSERT INTO muscle_emphasis (muscle, weight, note) VALUES "
        "('side_delts', 1.0, 't'), ('lats', 1.0, 't')"
    )
    build = "\n".join(_goal_lines(conn))
    assert "PRIMARY GOAL: build muscle" in build
    assert "lats and side delts" in build
    _set_phase(conn, "cut")
    cut = "\n".join(_goal_lines(conn))
    assert "lose midsection fat" in cut
    assert "150 min/week" in cut
    assert "lats and side delts" in cut
    assert "biceps" not in cut


def test_research_goals_follow_phase(conn):
    from shc import research

    assert research.goal_weights(conn)["muscle"] > research.goal_weights(conn)["body"]
    assert research.brief(conn)["rules"]["goals"].startswith("Build muscle first")
    _set_phase(conn, "cut")
    weights = research.goal_weights(conn)
    assert weights["body"] > weights["muscle"]
    assert set(weights) == set(research.GOAL_WEIGHTS)  # research_team validates goal keys
    assert research.brief(conn)["rules"]["goals"].startswith("Lose fat while keeping muscle")


def test_bodyweight_rate_needs_enough_weigh_ins_and_reads_loss_per_week():
    d0 = date(2026, 11, 1)
    assert _bodyweight_rate_pct_wk([(d0, 100.0), (d0 + timedelta(days=20), 98.0)]) is None
    pts = [(d0 + timedelta(days=i), 100.0 - 0.1 * i) for i in range(0, 15, 2)]
    assert round(_bodyweight_rate_pct_wk(pts), 2) == -0.70


def test_cut_tracking_excludes_pickleball_and_flags_blind_weight(conn):
    today = date(2026, 11, 16)
    conn.execute(
        "INSERT INTO cardio_sessions (id, date, modality, duration_min, content_hash) VALUES "
        "('a', ?, 'pickleball', 231, 'h'), ('b', ?, 'walking', 40, 'h'), "
        "('c', ?, 'cross country skiing', 60, 'h'), ('d', ?, 'walking', 90, 'h')",
        [today, today - timedelta(days=2), today, today - timedelta(days=7)],
    )
    text = "\n".join(_cut_tracking_lines(conn, today))
    assert "Non-court cardio: 40 / 150 min" in text
    assert "Pickleball 231 min" in text
    assert "about 4 workday-lunch session(s)" in text
    assert "UNMEASURED — 0 weigh-in(s)" in text


def _steps(conn: duckdb.DuckDBPyConnection, day: date, n: int) -> None:
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, external_id, content_hash) "
        "VALUES ('apple', 'step_count', ?, ?, ?, 'h')",
        [day, n, f"apple:{day}"],
    )


def test_cut_tracking_flags_a_step_drop_against_worn_baseline(conn):
    today = date(2026, 11, 16)
    for i in range(7, 30):
        _steps(conn, today - timedelta(days=i), 14000)
    for i in range(5):
        _steps(conn, today - timedelta(days=i), 6000)
    _steps(conn, today - timedelta(days=5), 300)  # Watch off: not a worn day
    text = "\n".join(_cut_tracking_lines(conn, today))
    assert "Steps: 6,000/day over 5 worn days vs 14,000 baseline" in text
    assert "-57%" in text
    assert "lunch walk" in text
