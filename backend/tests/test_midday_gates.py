from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

import pytest
from pydantic import ValidationError

from shc.ai.workout_planner import GateViolation, build_midday_context
from shc.api.routers import dashboard
from shc.metrics import ReadinessSnapshot, compute_daily_state


def session(
    kind: Literal["strength", "cardio", "mobility", "recovery"] = "cardio",
    intensity="high",
    **extra,
):
    return dashboard.MiddaySessionSubmission(
        session_type="mixed",
        title="Midday",
        duration_min=30,
        intensity=intensity,
        activities=[
            dashboard.MiddayActivity(name="Activity", kind=kind, duration_min=20, notes="Cues")
        ],
        rationale="Today's state",
        performance_goal="Training",
        **extra,
    )


def state():
    return {
        "gates": {"max_intensity": "high", "deload_required": False},
        "training_load": {"acwr": 1.0},
        "readiness": {"tier": "green"},
    }


@pytest.mark.parametrize("gate", ["rest", "low", "moderate"])
def test_midday_rejects_intensity_above_gate(conn, gate):
    today = state()
    today["gates"]["max_intensity"] = gate
    with pytest.raises(GateViolation):
        dashboard._validate_midday(session(), today, conn)


def test_midday_cannot_hide_cardio_as_passive(conn):
    with pytest.raises(GateViolation):
        dashboard._validate_midday(session(intensity="passive"), state(), conn)


@pytest.mark.parametrize("restriction", ["deload", "legs", "acwr"])
def test_midday_rejects_restricted_cardio(conn, restriction):
    today = state()
    if restriction == "deload":
        today["gates"]["deload_required"] = True
    elif restriction == "legs":
        today["gates"]["forbid_muscle_groups"] = ["legs"]
    else:
        today["training_load"]["acwr"] = 1.6
    with pytest.raises(GateViolation):
        dashboard._validate_midday(session(), today, conn)


def test_midday_allows_fresh_clear_cardio_and_passive_rest(conn):
    dashboard._validate_midday(session(), state(), conn)
    today = state()
    today["gates"].update(max_intensity="rest", deload_required=True)
    dashboard._validate_midday(session(kind="recovery", intensity="passive"), today, conn)


def test_strength_requires_structured_plan(conn):
    with pytest.raises(ValueError, match="structured strength_plan"):
        dashboard._validate_midday(session(kind="strength"), state(), conn)


def test_strength_uses_full_validator(conn, monkeypatch):
    monkeypatch.setattr("shc.ai.vault.valid_citation_filenames", lambda: set())
    called = []

    def reject(plan, **kwargs):
        called.append(kwargs)
        raise GateViolation("forbidden muscle")

    monkeypatch.setattr(dashboard, "validate_plan", reject)
    plan = {"recommendation": {"intensity": "high"}, "blocks": []}
    with pytest.raises(GateViolation, match="forbidden muscle"):
        dashboard._validate_midday(session(kind="strength", strength_plan=plan), state(), conn)
    assert called[0]["conn"] is conn
    assert called[0]["state"]["gates"]["max_intensity"] == "high"


@pytest.mark.parametrize("duration", [-1, 0, 61])
def test_invalid_activity_duration(duration):
    with pytest.raises(ValidationError):
        dashboard.MiddayActivity(name="Bike", kind="cardio", duration_min=duration, notes="")


@pytest.mark.parametrize(
    "age, expected", [(0, "high"), (2, "high"), (3, "moderate"), (5, "moderate")]
)
def test_recovery_freshness_boundary(conn, monkeypatch, age, expected):
    monkeypatch.setattr(
        "shc.metrics._readiness_snapshot", lambda *args, **kwargs: ReadinessSnapshot(tier="green")
    )
    conn.execute(
        "INSERT INTO recovery (id, date, source, content_hash, score, hrv, rhr) "
        "VALUES ('freshness', ?, 'whoop', 'freshness', 90, 120, 45)",
        [date.today() - timedelta(days=age)],
    )
    assert compute_daily_state(conn)["gates"]["max_intensity"] == expected


def test_midday_prompt_uses_effort_on_beta_blocker_day(conn, seed):
    seed.checkin(date.today(), propranolol_taken=True)
    prompt = build_midday_context(conn)
    assert "130–145" not in prompt
    assert "Beta-blocker taken today" in prompt
    assert "strength_plan" in prompt
