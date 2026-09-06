"""Guard the daily-report prompt against schema drift.

`_PROMPT` used to carry its own copy of the workout-plan schema. That copy
omitted `recommendation.target_rpe`, which `validate_plan` requires on every
non-rest, non-deload plan — so the prompt instructed the model to build a plan
the API rejects with a 422. Commit d566a6d deleted the copy and pointed at the
canonical `## OUTPUT SCHEMA` block inside `/api/workout/context`.

These tests hold that shape: one schema, one place, and a prompt whose stated
requirements still line up with what the validator actually enforces.
"""

from __future__ import annotations

import pathlib
import re

import pytest

import shc.ai.workout_planner as workout_planner
from shc.ai.workout_planner import validate_plan
from shc.api.routers.report import _PROMPT

# The heading the prompt tells the model to build against. Renaming it in
# workout_planner without updating the prompt leaves a dangling pointer.
SCHEMA_HEADING = "## OUTPUT SCHEMA"

# Plan fields the prompt names as required. Each is either a hard validator
# reject or a field the dashboard renders (see `test_canonical_schema_covers_*`).
PROMPT_REQUIRED_FIELDS = (
    "readiness_summary",
    "recommendation.target_rpe",
    "recommendation.summary",
    "recommendation.rationale",
    "recommendation.estimated_duration_min",
    "warmup",
    "rest_seconds",
    "clinical_notes",
)


def _canonical_schema() -> str:
    """The TypeScript schema block the context builder emits, as source text.

    Read from the module file rather than by calling the builder, which needs a
    live DB. The block is the single copy of the contract the validator enforces.
    """
    src = pathlib.Path(workout_planner.__file__).read_text()
    start = src.index(SCHEMA_HEADING)
    fence = src.index("```typescript", start)
    end = src.index("```", fence + len("```typescript"))
    return src[start:end]


# ── the prompt must not carry a rival schema ─────────────────────────────────


def test_prompt_has_no_fenced_schema_block() -> None:
    """A second schema definition is a second thing to drift. There is one."""
    assert "```" not in _PROMPT, "prompt regrew a fenced code block — likely a rival schema"
    assert "interface Plan" not in _PROMPT
    assert '"blocks":' not in _PROMPT, "prompt restates the plan shape as a JSON literal"


def test_prompt_points_at_the_canonical_schema() -> None:
    assert SCHEMA_HEADING in _PROMPT
    assert "/api/workout/context" in _PROMPT


def test_canonical_schema_heading_still_exists() -> None:
    """The pointer only works while the heading it names is really there."""
    assert SCHEMA_HEADING in pathlib.Path(workout_planner.__file__).read_text()


# ── prompt requirements vs the canonical schema ──────────────────────────────


@pytest.mark.parametrize("field", PROMPT_REQUIRED_FIELDS)
def test_prompt_names_each_required_field(field: str) -> None:
    """These are the fields models actually drop; the prompt must keep calling
    them out even though the schema itself lives elsewhere."""
    leaf = field.split(".")[-1]
    assert leaf in _PROMPT, f"prompt no longer mentions {field}"


@pytest.mark.parametrize("field", PROMPT_REQUIRED_FIELDS)
def test_canonical_schema_declares_each_prompt_requirement(field: str) -> None:
    """A field the prompt demands but the schema doesn't declare is stale copy."""
    leaf = field.split(".")[-1]
    assert leaf in _canonical_schema(), f"{field} named in the prompt but absent from the schema"


def test_canonical_schema_covers_the_fields_the_frontend_renders() -> None:
    """`WorkoutPlan` in frontend/lib/api.ts and next-workout.tsx read these.

    Drop one from the schema and the model stops emitting it — the card renders
    a blank WHY block or a "~ min" duration instead of failing loudly.
    """
    schema = _canonical_schema()
    for field in (
        "readiness_tier",
        "readiness_summary",
        "summary",
        "rationale",
        "estimated_duration_min",
        "target_rpe",
        "warmup",
        "blocks",
        "cooldown",
        "clinical_notes",
        "vault_insights",
    ):
        assert re.search(rf"\b{field}\b", schema), f"schema dropped {field}"


# ── a plan built from the prompt's requirements must validate ────────────────

STATE = {
    "gates": {
        "max_intensity": "moderate",
        "deload_required": False,
        "forbid_muscle_groups": [],
        "forbid_muscles": [],
        "reasons": [],
    }
}


def _plan_from_prompt_requirements() -> dict:
    """The minimum plan the prompt's stated requirements describe."""
    return {
        "readiness_tier": "yellow",
        "readiness_summary": "Recovery is middling; volume held steady.",
        "recommendation": {
            "intensity": "moderate",
            "focus": "upper",
            "summary": "Upper body today — your legs are still catching up from the weekend.",
            "rationale": "Pull volume 6/12 for the week; conditioning ACWR 1.2 leaves room.",
            "estimated_duration_min": 55,
            "target_rpe": 8,
        },
        "warmup": [{"name": "Rowing Machine", "sets": 1, "reps": "5 min"}],
        "blocks": [
            {
                "label": "A — Pull",
                "exercises": [
                    {
                        "name": "Face Pull",
                        "sets": 3,
                        "reps": "12",
                        "weight_lbs": 60,
                        "rpe_target": 8,
                        "rest_seconds": 90,
                        "notes": "Elbows high.",
                    }
                ],
            }
        ],
        "cooldown": "Five minutes easy walking.",
        "clinical_notes": ["propranolol PRN — HR zones shift low"],
        "vault_insights": ["effective-reps-hypertrophy.md"],
    }


def test_plan_built_from_the_prompt_passes_validation() -> None:
    assert validate_plan(_plan_from_prompt_requirements(), state=STATE) is True


def test_dropping_target_rpe_is_a_hard_reject() -> None:
    """The exact drift d566a6d fixed: schema without target_rpe → 422."""
    plan = _plan_from_prompt_requirements()
    del plan["recommendation"]["target_rpe"]
    with pytest.raises(ValueError, match="target_rpe"):
        validate_plan(plan, state=STATE)
