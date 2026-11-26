"""A question or experiment already put to the lab cannot come back under a new name."""

from __future__ import annotations

import pytest

from shc import research

SPEC = {
    "exposure": {"feature": "strain", "a": {"max": 10}, "b": {"min": 14}},
    "outcome": "lnhrv_dev_pct",
    "lag": 1,
    "unit": "day",
    "expected_sign": "-",
    "min_effect": 3,
}
CHANGED = "Adds a season covariate, which the earlier design was rejected for omitting."


def _rejected(conn) -> None:
    research.register(conn, "first", "q", SPEC, None, "recovery")
    conn.execute("UPDATE research_hypotheses SET status = 'rejected' WHERE slug = 'first'")


@pytest.mark.parametrize("spec", [SPEC, SPEC | {"min_effect": 4, "lag": 2}])
def test_a_rejected_question_cannot_return_unannounced(conn, spec) -> None:
    _rejected(conn)
    with pytest.raises(research.SpecError, match="first"):
        research.register(conn, "second", "q", spec, None, "recovery")


def test_a_repeat_must_say_what_changed(conn) -> None:
    _rejected(conn)
    spec = SPEC | {"min_effect": 4}
    with pytest.raises(research.SpecError, match="what_changed"):
        research.register(conn, "second", "q", spec, None, "recovery", follows="first")
    made = research.register(
        conn, "second", "q", spec, None, "recovery", follows="first", what_changed=CHANGED
    )
    assert made["slug"] == "second"


def test_a_different_question_needs_nothing(conn) -> None:
    _rejected(conn)
    other = SPEC | {"exposure": {"feature": "steps", "a": {"max": 5}, "b": {"min": 9}}}
    assert research.register(conn, "second", "q", other, None, "recovery")


BODY = "Design: daily. Factor: caffeine cutoff. Outcome: deep_sleep_min, higher is better."


def _decided(conn) -> None:
    pid = research.note(conn, "recovery", "proposal", "Experiment proposal: caffeine", BODY)
    research.note(
        conn, "methodologist", "review", "Experiment review: caffeine: rejected", "r", pid
    )


def test_a_proposal_names_its_factor_and_outcome(conn) -> None:
    with pytest.raises(research.SpecError, match="Factor"):
        research.check_proposal(conn, "Experiment proposal: x", "Design: daily.")


def test_a_decided_proposal_needs_follows_to_return(conn) -> None:
    _decided(conn)
    again = BODY.replace("Design: daily.", "Design: daily, min_effect 14.")
    with pytest.raises(research.SpecError, match="caffeine"):
        research.check_proposal(conn, "Experiment proposal: new name", again)
    research.check_proposal(
        conn,
        "Experiment proposal: new name",
        again + " Follows: caffeine. What changed: adds a two-week log showing the arms differ.",
    )


def test_other_notes_are_not_checked(conn) -> None:
    research.check_proposal(conn, "Correction: something", "free text")
