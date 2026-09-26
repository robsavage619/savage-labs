"""Equipment Rob's gym lacks never reaches a plan (migration 0103).

Seated Back Extension was loggable, curated for lower_back, and the #2 menu pick,
so three daily plans in a row (2026-09-24..26) prescribed a machine the gym does
not have. These tests lock the menu, the rotation, the context and validator #25.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc.ai.workout_planner import GateViolation, build_training_context, validate_plan
from shc.training.autoregulation import _exercise_menu, evidence_menu, unavailable_exercises

_ABSENT = "Seated Back Extension"


def _publish(conn, names) -> None:
    for n in names:
        conn.execute(
            "INSERT INTO hevy_exercise_templates (id, title, primary_muscle_group) "
            "VALUES (?, ?, 'lower_back') ON CONFLICT DO NOTHING",
            [n, n],
        )


def _plan(name: str) -> dict:
    return {
        "readiness_tier": "green",
        "recommendation": {
            "intensity": "moderate",
            "focus": "posterior chain",
            "rationale": "x",
            "estimated_duration_min": 40,
            "target_rpe": 7,
        },
        "warmup": [{"name": "Walking", "sets": 1, "reps": 5}],
        "blocks": [
            {
                "label": "A",
                "exercises": [
                    {
                        "name": name,
                        "sets": 2,
                        "reps": "10",
                        "weight_lbs": None,
                        "rpe_target": 7,
                        "rest_seconds": 90,
                        "notes": "n",
                    }
                ],
            }
        ],
        "cooldown": "walk",
        "clinical_notes": ["propranolol PRN"],
        "vault_insights": ["a"],
    }


_STATE = {"gates": {"max_intensity": "high", "forbid_muscle_groups": [], "reasons": []}}


def test_migration_seeds_the_confirmed_absences(conn) -> None:
    absent = unavailable_exercises(conn)
    assert {
        "Seated Back Extension",
        "Glute Kickback (Machine)",
        "Standing Cable Glute Kickbacks",
    } <= set(absent)
    assert all(absent.values()), "every absence carries a note"


def test_curated_lower_back_menu_skips_the_absent_machine(conn) -> None:
    curated = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT exercise_name FROM exercise_science WHERE muscle = 'lower_back'"
        ).fetchall()
    ]
    assert _ABSENT in curated, "fixture no longer curates the machine, test proves nothing"
    _publish(conn, curated)

    picks = evidence_menu(conn, ["lower_back"]).get("lower_back", [])
    assert picks, "menu returned nothing — fixture regression, not a real pass"
    assert _ABSENT not in {p["exercise"] for p in picks}
    # Filtered before selection, so rotation can't swap it in either.
    assert not any(_ABSENT in (p.get("status") or "") for p in picks)


def test_absent_machine_never_swapped_in_for_a_stale_lead(conn, seed) -> None:
    """A lead past the rotation window must rotate to something the gym has."""
    curated = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT exercise_name FROM exercise_science WHERE muscle = 'lower_back'"
        ).fetchall()
    ]
    _publish(conn, curated)
    lead = next(n for n in sorted(curated) if n != _ABSENT)
    today = date.today()
    for w in range(10):
        seed.workout(today - timedelta(weeks=w, days=1), lead, [(40.0, 10)] * 3)

    picks = evidence_menu(conn, ["lower_back"]).get("lower_back", [])
    assert _ABSENT not in {p["exercise"] for p in picks}
    assert not any(_ABSENT in (p.get("status") or "") for p in picks)


def test_fallback_menu_skips_the_absent_machine(conn) -> None:
    mapped = {
        r[0]
        for r in conn.execute(
            "SELECT exercise_name FROM exercise_muscle_map WHERE primary_muscle = 'glutes'"
        ).fetchall()
    }
    assert "Kickback (Cable)" in mapped, "fixture no longer maps it, test proves nothing"
    names = {
        e["exercise"] for e in _exercise_menu(conn, ["glutes"], per_muscle=50).get("glutes", [])
    }
    assert names, "fallback menu empty — fixture regression"
    assert "Glute Kickback (Machine)" not in names
    assert "Kickback (Cable)" not in names


def test_validator_rejects_an_absent_machine_by_name(conn) -> None:
    _publish(conn, [_ABSENT])
    with pytest.raises(GateViolation, match=r"not available at Rob's gym: Seated Back Extension"):
        validate_plan(_plan(_ABSENT), state=_STATE, conn=conn)


def test_validator_passes_equipment_the_gym_has(conn) -> None:
    _publish(conn, ["Back Extension (Hyperextension)"])
    try:
        validate_plan(_plan("Back Extension (Hyperextension)"), state=_STATE, conn=conn)
    except GateViolation as exc:
        assert "not available at Rob's gym" not in str(exc)


def _section(text: str, header: str) -> str:
    if header not in text:
        return ""
    return text.split(header, 1)[1].split("\n## ", 1)[0]


def test_context_never_offers_the_absent_machine(conn, seed) -> None:
    """Catalog list, NEXT PRESCRIPTION and RE-ENTRY TARGETS all drop it.

    A recent logged session gives it a live anchor, the strongest path by which
    next_prescriptions would otherwise surface it.
    """
    from shc.ai.workout_planner import e1rm_by_exercise
    from shc.training.prescriptor import next_prescriptions

    _publish(conn, [_ABSENT, "Back Extension (Hyperextension)"])
    seed.workout(date.today() - timedelta(days=3), _ABSENT, [(30.0, 10)] * 3)
    today = date.today()
    raw = next_prescriptions(conn, _STATE["gates"], today, e1rm_by_exercise(conn, today))
    assert _ABSENT in {n.exercise for n in raw}, "control: without the filter it WOULD surface"

    text, _ = build_training_context(conn)
    catalog = _section(text, "## AVAILABLE HEVY EXERCISES")
    assert "- Back Extension (Hyperextension)" in catalog, "catalog missing — fixture regression"
    assert f"- {_ABSENT}\n" not in catalog + "\n"
    assert _ABSENT not in _section(text, "## NEXT PRESCRIPTION")
    assert _ABSENT not in _section(text, "## RE-ENTRY TARGETS")
