"""Prescribed weights must be loads the gym can actually produce.

Every test here is written to FAIL if the snapping fix is reverted — a fixture
that cannot fail is worse than no fixture. The reverted behaviour each one
catches is named in its docstring.
"""

from __future__ import annotations

from datetime import date

import pytest

from shc.training.load_mechanics import COMBINED_LOGGING_ENDED
from shc.training.loadable import (
    build_grids,
    loadable_grid,
    snap_plan_weights,
    snap_to_loadable,
)

LB = 2.20462
DAY = date(2026, 7, 1)


def _kg(lbs: float) -> float:
    return lbs / LB


def _log(seed, exercise: str, lbs: list[float], *, day: date = DAY, times: int = 4) -> None:
    """Log ``times`` sets at each pound value, so the grid clears the evidence bar."""
    for _ in range(times):
        seed.workout(day, exercise, [(_kg(v), 8) for v in lbs])


# ── The core defect ──────────────────────────────────────────────────────────


def test_a_weight_between_two_logged_notches_snaps_onto_one(conn, seed):
    """The audited defect: 235 lb on a machine that only offers 230 and 270.

    Reverted (no snapping) this reads 235 — a weight that cannot be loaded.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 250.0, 270.0])
    assert snap_to_loadable(conn, "Hip Thrust (Machine)", 235.0) == pytest.approx(230.0)
    assert snap_to_loadable(conn, "Hip Thrust (Machine)", 265.0) == pytest.approx(270.0)


def test_an_equidistant_weight_snaps_down_never_up(conn, seed):
    """A rounding decision must never silently make a set HEAVIER than asked.

    Reverted to a plain ``min(grid, key=distance)`` this returns 270 — Python's
    min keeps the first minimum, which is order-dependent, not intent-driven.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0])
    _log(seed, "Hip Thrust (Machine)", [250.0])
    assert snap_to_loadable(conn, "Hip Thrust (Machine)", 240.0) == pytest.approx(230.0)


def test_a_load_above_the_logged_max_is_never_clamped_back_down(conn, seed):
    """Beating a personal best is progression, not an error — clamping freezes it.

    Reverted to ``min(max(lbs, grid[0]), grid[-1])`` this returns 200, pinning
    Rob to his own history forever.
    """
    _log(seed, "Leg Press (Machine)", [160.0, 170.0, 180.0, 190.0, 200.0])
    snapped = snap_to_loadable(conn, "Leg Press (Machine)", 212.0)
    assert snapped > 200.0
    assert snapped == pytest.approx(210.0)  # extended on the grid's 10 lb step


def test_a_load_below_the_logged_minimum_is_never_snapped_up(conn, seed):
    """Snapping up is the one direction that can turn a deload into a harder set.

    Reverted to "nearest notch" this returns 60 for a prescribed 50 — a +20%
    move on a day whose whole intent was to back off.
    """
    _log(seed, "Chest Press (Machine)", [60.0, 80.0, 100.0])
    snap = build_grids(conn).snap("Chest Press (Machine)", 50.0)
    assert snap.weight_lbs == pytest.approx(50.0)
    assert snap.reason == "below-min"


# ── Scoping: the rack is gym-wide, the stack is per-machine ──────────────────


def test_a_dumbbell_grid_pools_across_the_whole_rack(conn, seed):
    """A dumbbell rack is gym-wide, so another lift's 70 proves 70 is loadable here.

    Reverted to a per-exercise dumbbell grid, ``Shrug (Dumbbell)`` (whose own
    history holds only 60) cuts a prescribed 70 to 60 — a -14.3% move justified
    by nothing but a thin history.
    """
    # Shrug's OWN history is well-sampled but skips 70 — enough to look like a
    # coarse rack if the grid is scoped per-exercise.
    _log(seed, "Shrug (Dumbbell)", [50.0, 60.0, 80.0], times=5)
    _log(seed, "Bench Press (Dumbbell)", [50.0, 60.0, 70.0, 80.0])
    assert snap_to_loadable(conn, "Shrug (Dumbbell)", 70.0) == pytest.approx(70.0)


def test_a_machine_grid_stays_per_exercise(conn, seed):
    """Each pin stack has its own pitch — pooling machines would invent notches.

    Reverted to one pooled machine grid, the Leg Extension's 235 leaks into the
    Hip Thrust's grid and a prescribed 235 stops snapping at all.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 250.0, 270.0])
    _log(seed, "Leg Extension (Machine)", [225.0, 230.0, 235.0, 240.0])
    assert snap_to_loadable(conn, "Hip Thrust (Machine)", 235.0) == pytest.approx(230.0)
    assert snap_to_loadable(conn, "Leg Extension (Machine)", 235.0) == pytest.approx(235.0)


# ── Evidence discipline ──────────────────────────────────────────────────────


def test_a_thin_history_may_not_argue_that_a_weight_does_not_exist(conn, seed):
    """A logged value proves a notch exists; a missing one proves only disinterest.

    Reverted to trusting any grid with 3+ notches, ``Crunch (Machine)`` — 9 real
    sets at 60/80/115 — cuts a prescribed 70 to 60, a -14.3% move.
    """
    seed.workout(DAY, "Crunch (Machine)", [(_kg(60.0), 12), (_kg(80.0), 12), (_kg(115.0), 12)])
    seed.workout(DAY, "Crunch (Machine)", [(_kg(60.0), 12), (_kg(80.0), 12), (_kg(115.0), 12)])
    snap = build_grids(conn).snap("Crunch (Machine)", 70.0)
    assert snap.weight_lbs == pytest.approx(70.0)
    assert snap.reason.startswith("thin-history")


def test_a_well_sampled_grid_still_bites(conn, seed):
    """The evidence bar must not become a blanket excuse to never snap.

    This is the guard against "fixing" the thin-history test by disabling
    snapping: Standing Calf Raise has real evidence and genuinely has no 430.
    """
    _log(seed, "Standing Calf Raise (Machine)", [360.0, 400.0, 495.0], times=8)
    assert snap_to_loadable(conn, "Standing Calf Raise (Machine)", 430.0) == pytest.approx(400.0)


def test_an_exercise_with_no_history_is_returned_unchanged_and_says_so(conn, seed):
    """No history is an equipment-availability signal, not a licence to guess."""
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0])
    snap = build_grids(conn).snap("Nautilus Pullover", 137.3)
    assert snap.weight_lbs == pytest.approx(137.3)
    assert snap.reason == "no-history"
    assert not snap.moved


# ── Per-hand semantics (invariant 19) ────────────────────────────────────────


def test_the_grid_is_measured_per_hand_not_as_logged(conn, seed):
    """Invariant 19: every load path reads through the per-hand choke point.

    Romanian Deadlift was logged as a two-dumbbell TOTAL before
    ``COMBINED_LOGGING_ENDED``, so a logged 150 IS 75 per hand and a prescribed
    75 is on the grid. Reverted to raw ``weight_kg`` the grid reads 150/hand,
    75 falls below its minimum, and the per-hand unit silently splits in two.
    """
    before = date(2026, 6, 11)
    assert before < COMBINED_LOGGING_ENDED
    _log(seed, "Romanian Deadlift (Dumbbell)", [90.0, 120.0, 150.0], day=before)
    grid = loadable_grid(conn, "Romanian Deadlift (Dumbbell)")
    assert 75.0 in grid
    assert max(grid) <= 105.0  # the confirmed one-hand maximum


def test_a_contaminated_row_never_becomes_a_phantom_dumbbell(conn, seed):
    """Pre-2026 Shrugs logged as two-dumbbell totals reach 220 lb per hand.

    Reverted (no ``exceeds_per_hand_max`` filter) those enter the shared rack,
    so a prescribed 180 lb dumbbell reads as "on-grid" and is never corrected.
    """
    _log(seed, "Shrug (Dumbbell)", [120.0, 160.0, 200.0, 220.0])
    _log(seed, "Bench Press (Dumbbell)", [60.0, 70.0, 80.0])
    rack = loadable_grid(conn, "Shrug (Dumbbell)")
    assert rack, "the rack must not be emptied by the filter"
    assert max(rack) <= 105.0


# ── kg round-trip noise ──────────────────────────────────────────────────────


def test_a_snap_lands_on_the_round_notch_not_the_kg_round_trip_artifact(conn, seed):
    """60 kg is 132.28 lb; the DB is kg-native so the same notch has two spellings.

    Reverted (no clustering) a prescribed 133 snaps to **132.3** — the snapper
    "fixing" an unloadable weight by emitting a number no stack displays.
    """
    _log(seed, "Seated Row (Cable)", [120.0, 132.0, 145.0])
    for _ in range(4):
        seed.workout(DAY, "Seated Row (Cable)", [(60.0, 8)])  # exactly 60 kg
    assert 132.3 not in loadable_grid(conn, "Seated Row (Cable)")
    assert snap_to_loadable(conn, "Seated Row (Cable)", 133.0) == pytest.approx(132.0)


# ── The plan-save wiring ─────────────────────────────────────────────────────


def _plan() -> dict:
    return {
        "blocks": [
            {
                "exercises": [
                    {"name": "Hip Thrust (Machine)", "weight_lbs": 235, "reps": "8-10"},
                    {"name": "Standing Calf Raise (Machine)", "weight_lbs": 430},
                    {"name": "Plank", "weight_lbs": 0},
                ]
            }
        ]
    }


def test_a_saved_plan_can_never_carry_an_unloadable_weight(conn, seed):
    """The load-bearing fix: snap before persisting, in place, with a visible note.

    Reverted (no call to ``snap_plan_weights``) the stored plan keeps 235 and 430
    — the exact numbers the audit found between two real notches.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 250.0, 270.0])
    _log(seed, "Standing Calf Raise (Machine)", [360.0, 400.0, 495.0], times=8)

    plan = _plan()
    moved = snap_plan_weights(conn, plan)

    exercises = plan["blocks"][0]["exercises"]
    assert exercises[0]["weight_lbs"] == pytest.approx(230.0)
    assert exercises[1]["weight_lbs"] == pytest.approx(400.0)
    assert exercises[2]["weight_lbs"] == 0  # bodyweight is left alone
    assert exercises[0]["snapped"]["from_lbs"] == 235
    assert "snapped" not in exercises[2]
    assert {s.exercise for s in moved} == {
        "Hip Thrust (Machine)",
        "Standing Calf Raise (Machine)",
    }


def test_the_plan_endpoint_snaps_before_it_persists(conn, seed):
    """The router must actually call the snapper, not just have it importable.

    Reverted (the call removed from ``submit_workout_plan``) this fails: the
    module-level name is gone from the endpoint's globals and the wiring is dead.
    """
    import inspect

    from shc.api.routers import dashboard

    src = inspect.getsource(dashboard.submit_workout_plan)
    assert "snap_plan_weights(conn, body.plan)" in src
    # ...and it must run BEFORE the plan is handed to save_plan.
    assert src.index("snap_plan_weights") < src.index("save_plan(")


# ── The anchors handed to the planner ────────────────────────────────────────


def test_a_ceiling_is_rounded_down_never_up(conn, seed):
    """A ceiling rounded UP to the next notch is no longer a ceiling.

    Reverted to nearest-notch snapping, a 268 lb ceiling becomes 270 — the
    validator's own bound handed to the planner two pounds above itself.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 250.0, 270.0])
    grids = build_grids(conn)
    assert grids.snap_down("Hip Thrust (Machine)", 268.0) == pytest.approx(250.0)
    assert grids.snap_up("Hip Thrust (Machine)", 268.0) == pytest.approx(270.0)


# ── Declared equipment facts (migration 0088) ────────────────────────────────


def _declare(conn, exercise: str, increment: float, anchor: float) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO equipment_increment "
        "(exercise_name, increment_lb, anchor_lb, note) VALUES (?, ?, ?, ?)",
        [exercise, increment, anchor, "test"],
    )


def test_a_declared_increment_fixes_the_case_history_is_too_thin_to_prove(conn, seed):
    """The complaint that started this work, and the reason overrides exist.

    Hip Thrust (Machine) has 9 real logged sets across exactly two weights. The
    evidence bar (`_MIN_SETS_TO_PROVE_A_GAP`) correctly refuses to argue any
    weight is absent on that little data, so 235 passes through untouched — the
    caution is right and the outcome is still wrong. Rob's declared fact (plate
    loaded, 10s smallest, loaded in pairs -> 20 lb step, phase anchored at 230)
    resolves it.

    Reverted (overrides not consulted) this reads 235.0.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0], times=4)
    _declare(conn, "Hip Thrust (Machine)", 20.0, 230.0)
    grids = build_grids(conn)
    assert grids.snap("Hip Thrust (Machine)", 235.0).weight_lbs == pytest.approx(230.0)
    # The lattice extends both ways from the anchor, not from zero.
    assert grids.snap("Hip Thrust (Machine)", 262.0).weight_lbs == pytest.approx(270.0)
    assert grids.snap("Hip Thrust (Machine)", 215.0).weight_lbs == pytest.approx(210.0)


def test_a_declared_increment_outranks_a_thin_inferred_grid(conn, seed):
    """Declared beats inferred — otherwise the override is dead on the lifts it targets.

    A thin history would route to the name-inferred 5 lb fallback and answer 235.
    The declaration must win. Reverted, this returns 235.0 via `thin-history`.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0], times=1)
    _declare(conn, "Hip Thrust (Machine)", 20.0, 230.0)
    snap = build_grids(conn).snap("Hip Thrust (Machine)", 235.0)
    assert snap.weight_lbs == pytest.approx(230.0)
    assert "declared" in snap.reason


def test_a_declared_lattice_still_never_rounds_a_ceiling_up(conn, seed):
    """Overrides must honour the bound semantics, not just the nearest-notch rule."""
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0])
    _declare(conn, "Hip Thrust (Machine)", 20.0, 230.0)
    grids = build_grids(conn)
    assert grids.snap_down("Hip Thrust (Machine)", 245.0) == pytest.approx(230.0)
    assert grids.snap_up("Hip Thrust (Machine)", 245.0) == pytest.approx(250.0)
    # An exact lattice value is already loadable and must not be moved either way.
    assert grids.snap_down("Hip Thrust (Machine)", 250.0) == pytest.approx(250.0)
    assert grids.snap_up("Hip Thrust (Machine)", 250.0) == pytest.approx(250.0)


def test_an_undeclared_exercise_is_unaffected_by_the_override_table(conn, seed):
    """Scoping guard: one declaration must not become a global step.

    Without this, "declare an increment" could quietly re-round every other lift.
    """
    _log(seed, "Hip Thrust (Machine)", [230.0, 270.0])
    _log(seed, "Leg Extension (Machine)", [160.0, 165.0, 170.0, 175.0])
    _declare(conn, "Hip Thrust (Machine)", 20.0, 230.0)
    grids = build_grids(conn)
    assert grids.snap("Leg Extension (Machine)", 166.0).weight_lbs == pytest.approx(165.0)
    assert "declared" not in grids.snap("Leg Extension (Machine)", 166.0).reason
