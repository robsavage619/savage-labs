from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

from shc.api.routers.dashboard import (
    _FIB4_CAVEAT,
    _age_at,
    _fib4,
    _fib4_band,
    _fib4_by_draw,
)
from shc.ingest.clinical_profile import subject_dob

# SYNTHETIC birthday — not Rob's. The real DOB lives in the gitignored clinical
# profile because this repo is public (see dashboard._fib4_by_draw); the age it
# implies is already public everywhere (`metrics._ROB_AGE`), the exact date is
# not. Chosen to put age 40 at `_ROB_DRAW` so the real-draw score below is still
# the real number. The one test that reads the CONFIGURED DOB skips when no
# profile is present, so this suite passes on a fresh clone.
_DOB = date(1986, 1, 1)

# Rob's 2026-09-04 draw — the value this feature exists to stop him computing by
# hand. age 40, AST 37, ALT 64, platelets 276 → 1480 / (276 * 8) = 0.6703.
_ROB_DRAW = datetime(2026, 9, 4, 15, 17)


def _rows(*specs: tuple[str, float, datetime]) -> list[tuple]:
    return [(n, v, ts) for n, v, ts in specs]


def test_rob_current_draw_is_067():
    assert _fib4(40, 37.0, 64.0, 276.0) == pytest.approx(0.6703, abs=1e-4)


def test_configured_dob_agrees_with_the_rob_age_constant():
    """The profile's DOB must reproduce metrics._ROB_AGE, or two ages of Rob exist."""
    from shc.metrics import _ROB_AGE

    dob = subject_dob()
    if dob is None:
        pytest.skip("no clinical profile on this machine — nothing to reconcile")
    assert _age_at(dob, date(2026, 9, 5)) == _ROB_AGE


def test_age_at_draw_not_age_today():
    """A draw before the birthday scores a year younger."""
    assert _age_at(_DOB, date(2025, 12, 31)) == 39
    assert _age_at(_DOB, date(2026, 1, 1)) == 40


def test_bands():
    assert _fib4_band(0.67) == "rule_out"
    assert _fib4_band(1.29) == "rule_out"
    assert _fib4_band(1.30) == "indeterminate"
    assert _fib4_band(2.67) == "indeterminate"
    assert _fib4_band(2.68) == "rule_in"


def test_non_positive_inputs_return_none():
    assert _fib4(40, 0.0, 64.0, 276.0) is None
    assert _fib4(40, 37.0, 0.0, 276.0) is None
    assert _fib4(40, 37.0, 64.0, 0.0) is None


def test_by_draw_scores_robs_draw():
    out = _fib4_by_draw(
        _rows(
            ("AST", 37.0, _ROB_DRAW),
            ("ALT", 64.0, _ROB_DRAW),
            ("Platelet Count", 276.0, _ROB_DRAW),
        ),
        dob=_DOB,
    )
    assert len(out) == 1
    e = out[0]
    assert e["value"] == 0.67
    assert e["band"] == "rule_out"
    assert e["age_at_draw"] == 40
    assert e["missing_inputs"] == []
    assert str(_ROB_DRAW) in e["collected_at"]


def test_incomplete_draw_is_null_never_borrowed():
    """The failure this feature must not have: an AST from one draw scored
    against a platelet count from another."""
    old = datetime(2023, 12, 3, 15, 29)
    out = _fib4_by_draw(
        _rows(
            ("AST", 37.0, _ROB_DRAW),
            ("ALT", 64.0, _ROB_DRAW),
            ("Platelet Count", 276.0, _ROB_DRAW),
            # The old draw has only a platelet count. If it were allowed to reach
            # forward — or the new AST/ALT to reach back — this scores anyway.
            ("Platelet Count", 150.0, old),
        ),
        dob=_DOB,
    )
    by_ts = {e["collected_at"]: e for e in out}
    stale = by_ts[str(old)]
    assert stale["value"] is None
    assert stale["band"] is None
    assert sorted(stale["missing_inputs"]) == ["ALT", "AST"]
    # And the complete draw is unaffected by the stray row.
    assert by_ts[str(_ROB_DRAW)]["value"] == 0.67


def test_history_is_newest_first():
    older = datetime(2024, 3, 26, 17, 25)
    out = _fib4_by_draw(
        _rows(
            ("AST", 30.0, older),
            ("ALT", 30.0, older),
            ("Platelet Count", 250.0, older),
            ("AST", 37.0, _ROB_DRAW),
            ("ALT", 64.0, _ROB_DRAW),
            ("Platelet Count", 276.0, _ROB_DRAW),
        ),
        dob=_DOB,
    )
    assert [e["collected_at"] for e in out] == [str(_ROB_DRAW), str(older)]
    # Age is re-derived per draw, not reused.
    assert out[0]["age_at_draw"] == 40
    assert out[1]["age_at_draw"] == 38


def test_caveat_does_not_read_as_an_all_clear():
    lower = _FIB4_CAVEAT.lower()
    assert "steatosis" in lower
    assert "not an all-clear" in lower


def test_end_to_end_against_a_seeded_labs_table(conn: duckdb.DuckDBPyConnection):
    """Same SQL the endpoint runs, against the real `labs` schema."""
    for i, (name, value, ts) in enumerate(
        [
            ("AST", 37.0, _ROB_DRAW),
            ("ALT", 64.0, _ROB_DRAW),
            ("Platelet Count", 276.0, _ROB_DRAW),
            ("HbA1c", 5.4, datetime(2026, 4, 27, 10, 38)),
        ]
    ):
        conn.execute(
            "INSERT INTO labs (id, name, value, unit, collected_at) VALUES (?, ?, ?, ?, ?)",
            [f"t{i}", name, value, "unit/L", ts],
        )
    rows = conn.execute(
        """
        SELECT name, value, collected_at
        FROM labs
        WHERE name IN ('AST', 'ALT', 'Platelet Count')
          AND value IS NOT NULL AND collected_at IS NOT NULL
        """
    ).fetchall()
    out = _fib4_by_draw(rows, dob=_DOB)
    assert len(out) == 1
    assert out[0]["value"] == 0.67
    assert out[0]["band"] == "rule_out"


def test_absent_dob_refuses_to_score_rather_than_using_todays_age():
    """No profile → no FIB-4, and the payload says which input is missing.

    The tempting fallback is `metrics._ROB_AGE`, which would score a 2023 draw
    with a 2026 age — the exact error the per-draw age exists to prevent.
    """
    out = _fib4_by_draw(
        _rows(
            ("AST", 37.0, _ROB_DRAW),
            ("ALT", 64.0, _ROB_DRAW),
            ("Platelet Count", 276.0, _ROB_DRAW),
        ),
        dob=None,
    )
    assert len(out) == 1
    assert out[0]["value"] is None
    assert out[0]["band"] is None
    assert "patient.dob (clinical profile)" in out[0]["missing_inputs"]
