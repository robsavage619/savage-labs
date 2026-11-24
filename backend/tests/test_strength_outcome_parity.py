"""Pin the engine's e1RM so the lab's re-implementation of it cannot drift silently.

The lab outcome ``custom:session_e1rm_vs28d`` is SQL stored in the DB table
``research_custom_features``; it re-implements the engine e1RM (Epley over
RIR-adjusted reps, per-hand load) outside ``training/load_mechanics.py``. That
SQL text lives only in the live DB, so this repo cannot execute it at test time
and nothing here proves the two agree (ENGINE_INVARIANTS 13). What CAN be pinned
is the engine side, against an independent recompute (invariant 18: expected
values come from the spec written out below, never from the SQL helpers), plus
the literals the stored SQL hardcodes. If any of these change, the stored SQL
must be re-reviewed and the feature re-approved.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc.training import load_mechanics as lm
from shc.training.mesocycle import _CAPPED_E1RM

# Literals the stored lab SQL hardcodes today. Changing a switch date or the
# combined-logging set in the engine without updating the lab SQL reopens F12.
LAB_RDL_SWITCH = date(2026, 7, 23)
LAB_CURL_SWITCH = date(2026, 9, 24)
LAB_COMBINED_LIFTS = {"romanian deadlift (dumbbell)", "seated dumbbell curl"}
LAB_RIR_CREDIT_CAP = 3
LAB_REP_CAP = 12


def _expected_e1rm(logged_kg: float, reps: int, rpe: float | None, halve: bool = False) -> float:
    """Epley over RIR-adjusted reps, written from the spec, not the engine SQL."""
    credit = 0 if rpe is None else max(min(10 - rpe, LAB_RIR_CREDIT_CAP), 0)
    eff = min(reps + credit, LAB_REP_CAP)
    load = logged_kg / 2.0 if halve else logged_kg
    return load * (1 + eff / 30.0)


# (exercise, day, logged_kg, reps, rpe, halved by the lab's convention)
_D = date(2026, 11, 2)
CASES = [
    ("Bench Press (Barbell)", _D, 100.0, 8, None, False),  # no RPE: no RIR credit
    ("Row (Barbell)", _D, 100.0, 8, 7.0, False),  # 3 RIR credit
    ("Squat (Barbell)", _D, 100.0, 12, 7.0, False),  # cap binds AFTER adjustment
    ("Press (Machine)", _D, 100.0, 10, 5.0, False),  # RIR credit clamps at 3
    ("Fly (Machine)", _D, 100.0, 8, 10.0, False),  # RPE 10: zero credit
    ("Raise (Cable)", _D, 100.0, 15, None, False),  # cap binds with no RPE
    ("Romanian Deadlift (Dumbbell)", LAB_RDL_SWITCH - timedelta(days=1), 150.0, 5, None, True),
    ("Romanian Deadlift (Dumbbell)", LAB_RDL_SWITCH, 75.0, 5, None, False),
    ("Romanian Deadlift (Dumbbell)", LAB_RDL_SWITCH - timedelta(days=2), 150.0, 8, 8.0, True),
    ("Seated Dumbbell Curl", LAB_CURL_SWITCH - timedelta(days=1), 100.0, 8, 7.0, True),
    ("Seated Dumbbell Curl", LAB_CURL_SWITCH, 50.0, 8, 7.0, False),
    ("Single Leg Romanian Deadlift (Dumbbell)", _D, 40.0, 8, None, False),
]


def test_engine_e1rm_matches_independent_recompute(conn, seed) -> None:
    for ex, day, kg, reps, rpe, _ in CASES:
        seed.workout(day, ex, [(kg, reps)], rpe=rpe)
    rows = conn.execute(
        f"SELECT exercise, started_at::DATE, weight_kg, reps, {_CAPPED_E1RM} "
        "FROM workout_sets_dedup"
    ).fetchall()
    got = {(r[0], r[1], r[2], r[3]): r[4] for r in rows}
    assert len(got) == len(CASES)
    for ex, day, kg, reps, rpe, halve in CASES:
        assert got[(ex, day, kg, reps)] == pytest.approx(_expected_e1rm(kg, reps, rpe, halve)), (
            ex,
            day,
            rpe,
        )


def test_missing_rpe_adds_no_rir_credit() -> None:
    assert _expected_e1rm(100, 8, None) == pytest.approx(100 * (1 + 8 / 30))
    assert _expected_e1rm(100, 8, 7) > _expected_e1rm(100, 8, None)


def test_lab_sql_hardcoded_literals_still_match_engine() -> None:
    assert lm.COMBINED_LOGGING_ENDED == LAB_RDL_SWITCH
    assert lm.SEATED_CURL_COMBINED_LOGGING_ENDED == LAB_CURL_SWITCH
    assert set(lm._LOGGED_AS_COMBINED) == LAB_COMBINED_LIFTS
    assert lm.MAX_RIR_CREDIT == LAB_RIR_CREDIT_CAP
    assert lm.EPLEY_REP_CAP == LAB_REP_CAP
