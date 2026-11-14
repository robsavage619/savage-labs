"""Cut phase: volume tops out at MAV, and the planner prompt follows the stored phase."""

from __future__ import annotations

import duckdb

from shc.ai.workout_planner import _goal_lines
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
