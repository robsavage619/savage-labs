"""The subject's big questions order what the lab does next."""

from __future__ import annotations

import pytest

from shc import research, research_team

ROADMAP = {
    "questions": [
        {"id": "first", "question": "q1", "changes": "c1", "status": "open", "needs": "a design"},
        {"id": "second", "question": "q2", "changes": "c2", "status": "open", "needs": ""},
        {"id": "shelved", "question": "q3", "changes": "c3", "status": "parked", "needs": ""},
    ],
    "will_do": ["one-tap"],
    "will_not_do": ["food log"],
    "off_limits": ["a sport"],
}


def _agenda(conn, who: str, *leads: tuple[str, int, str]) -> None:
    research_team.set_agenda(
        conn,
        who,
        {
            "interests": "i",
            "hunches": "h",
            "next_steps": "n",
            "open_leads": [
                {"lead": text, "why": "w", "priority": pri, "status": "open"}
                | ({"serves": serves} if serves else {})
                for text, pri, serves in leads
            ],
        },
    )


def test_next_follows_the_subjects_order_not_the_agents_priority(conn) -> None:
    research.set_roadmap(conn, ROADMAP)
    _agenda(conn, "recovery", ("unserved", 1, ""), ("parked", 1, "shelved"), ("b", 1, "second"))
    _agenda(conn, "metabolic", ("a", 5, "first"))
    know = research.knowledge(conn)
    assert [x["lead"] for x in know["next"]] == ["a", "b", "unserved", "parked"]
    assert know["roadmap"] == ROADMAP
    assert [q["id"] for q in know["needs_you"]] == ["first"]


def test_the_latest_roadmap_wins_and_survives_other_notes(conn) -> None:
    research.set_roadmap(conn, ROADMAP)
    research.set_roadmap(conn, ROADMAP | {"off_limits": ["two"]})
    assert (research.roadmap(conn) or {})["off_limits"] == ["two"]


def test_a_roadmap_must_be_well_formed(conn) -> None:
    with pytest.raises(research.SpecError):
        research.set_roadmap(conn, ROADMAP | {"questions": [{"id": "x"}]})
    assert research.roadmap(conn) is None
