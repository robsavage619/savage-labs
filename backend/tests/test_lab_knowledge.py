"""The lab's standing memory: nothing in it may age out of the brief."""

from __future__ import annotations

import re
from pathlib import Path

import shc
from shc import research, research_team

_METHODOLOGIST = (
    Path(shc.__file__).resolve().parents[3] / ".claude/agents/research-methodologist.md"
)


def _question(conn, slug: str, status: str, verdict: str | None = None) -> None:
    conn.execute(
        "INSERT INTO research_hypotheses (id, slug, question, spec, spec_hash, author, status) "
        "VALUES (?, ?, ?, '{}', ?, 'recovery', ?)",
        [slug, slug, f"question {slug}", slug, status],
    )
    if verdict:
        conn.execute(
            "INSERT INTO research_results (id, hypothesis_id, verdict, effect) VALUES (?, ?, ?, 1.5)",
            [slug, slug, verdict],
        )


def test_old_findings_survive_a_flood_of_newer_notes(conn) -> None:
    research.note(conn, "recovery", "exploration", "old finding", "x\nCloses lead: naps")
    research.note(conn, "lab lead", "note", "Correction: old claim retracted", "why")
    for i in range(120):
        research.note(conn, "recovery", "note", f"later {i}")
    know = research.knowledge(conn)
    assert [(e["title"], e["lead"]) for e in know["explored"]] == [
        ("old finding", "Closes lead: naps")
    ]
    assert [c["title"] for c in know["corrections"]] == ["Correction: old claim retracted"]


def test_questions_are_sorted_by_what_they_settled(conn) -> None:
    _question(conn, "yes", "active", "supported")
    _question(conn, "no", "active", "ruled_out")
    _question(conn, "unclear", "retired", "inconclusive")
    _question(conn, "refused", "rejected")
    research.note(conn, "methodologist", "rejection", "Rejected: q", "arms too close", "refused")
    know = research.knowledge(conn)
    assert [q["slug"] for q in know["established"]] == ["yes"]
    assert [q["slug"] for q in know["ruled_out"]] == ["no"]
    unsettled = {q["slug"]: q for q in know["not_settled"]}
    assert unsettled["refused"]["why"] == "arms too close"
    assert set(unsettled) == {"unclear", "refused"}


def test_proposals_gaps_and_next_leads(conn) -> None:
    pid = research.note(conn, "recovery", "proposal", "Experiment proposal: naps", "d")
    research.note(conn, "methodologist", "review", "Experiment review: naps: rejected", "r", pid)
    research.note(conn, "recovery", "exploration", "Design gap: blocks", "x")
    lead = {"why": "w", "status": "open"}
    research_team.set_agenda(
        conn,
        "recovery",
        {
            "interests": "i",
            "hunches": "h",
            "next_steps": "n",
            "open_leads": [
                {**lead, "lead": "minor", "priority": 3},
                {**lead, "lead": "done", "priority": 1, "status": "closed"},
            ],
        },
    )
    research_team.set_agenda(
        conn,
        "hypertrophy",
        {
            "interests": "i",
            "hunches": "h",
            "next_steps": "n",
            "open_leads": [{**lead, "lead": "major", "priority": 1}],
        },
    )
    know = research.knowledge(conn)
    assert [(p["title"], p["verdict"]) for p in know["experiment_proposals"]] == [
        ("Experiment proposal: naps", "rejected")
    ]
    assert [g["title"] for g in know["design_gaps"]] == ["Design gap: blocks"]
    assert [x["lead"] for x in know["next"]] == ["major", "minor"]
    assert research.brief(conn)["knowledge"] == know


def test_methodologist_history_query_shows_designs_and_verdicts_only(conn) -> None:
    found = re.search(r"`(SELECT q\.title.*?ORDER BY q\.written_at)`", _METHODOLOGIST.read_text())
    assert found, "the history query is gone from the methodologist prompt"
    research_team.check_sql(conn, found.group(1))
    pid = research.note(conn, "recovery", "proposal", "Experiment proposal: naps", "d")
    research.note(conn, "methodologist", "review", "Experiment review: naps: rejected", "why", pid)
    assert conn.execute(found.group(1)).fetchall() == [
        ("Experiment proposal: naps", "d", "Experiment review: naps: rejected")
    ]
