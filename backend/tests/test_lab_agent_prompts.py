"""The research agents' prompts must agree with the code they drive.

The prompts are markdown, so nothing else notices when a build changes the outcomes,
routes or tables they name. These checks are the cheap half; the behaviour half is
``scripts/lab_agent_eval.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import shc
from shc import daily_candidates, research, research_team, selflab
from shc.api.main import app

_ROOT = Path(shc.__file__).resolve().parents[3]
_AGENTS = _ROOT / ".claude" / "agents"
_LAB_JOB = _ROOT / "deploy" / "jobs" / "lab.md"
_DAILY_AUTHORS = ("recovery", "conditioning", "metabolic")
_DOCS = [*sorted(_AGENTS.glob("research-*.md")), _LAB_JOB]
_DAILY_OUTCOMES = {m for m in selflab.SUPPORTED_OUTCOME_METRICS if m != "top_set_e1rm"}


def _agent(name: str) -> str:
    return (_AGENTS / f"research-{name}.md").read_text()


def _names_daily_outcomes(line: str) -> set[str]:
    return set(re.findall(r"`([a-z_0-9]+)`", line.split("outcome", 1)[1]))


@pytest.mark.parametrize("name", [*_DAILY_AUTHORS, "methodologist"])
def test_daily_outcomes_match_the_code(name: str) -> None:
    lines = [ln for ln in _agent(name).splitlines() if "`rhr_next_morning`" in ln]
    assert lines, f"{name} never lists the daily outcomes"
    listed = _names_daily_outcomes(lines[0]) & (_DAILY_OUTCOMES | {"top_set_e1rm"})
    assert listed == _DAILY_OUTCOMES


@pytest.mark.parametrize("doc", _DOCS, ids=lambda p: p.name)
def test_every_api_route_a_prompt_names_exists(doc: Path) -> None:
    served = [re.sub(r"\{[^}]+\}", "X", getattr(r, "path", "")) for r in app.routes]
    patterns = [re.compile("^" + p.replace("X", "[^/]+") + "$") for p in served]
    named = re.findall(
        r"(?:GET|POST|PUT|localhost:8000)\s*`?(?:http://localhost:8000)?(/api/[\w\-/{}<>]+)",
        doc.read_text(),
    )
    named += re.findall(r"`(?:GET |POST |PUT )?(/api/[\w\-/{}<>]+)", doc.read_text())
    for path in named:
        concrete = re.sub(r"\{[^}]+\}|<[^>]+>", "x", path.rstrip("/"))
        assert any(p.match(concrete) for p in patterns), f"{doc.name} names {path}"


@pytest.mark.parametrize("name", _DAILY_AUTHORS)
def test_candidate_slugs_a_prompt_names_are_real(name: str) -> None:
    named = {c.slug for c in daily_candidates.CANDIDATES}
    assert all(slug in _agent(name) for slug in named)


def test_methodologist_query_finds_only_unreviewed_proposals(conn) -> None:
    sql = re.search(r"`(SELECT p\.id.*?ORDER BY p\.written_at)`", _agent("methodologist"))
    assert sql, "the proposal query is gone from the methodologist prompt"
    research_team.check_sql(conn, sql.group(1))
    done = research.note(conn, "recovery", "proposal", "Experiment proposal: old", "d")
    research.note(conn, "methodologist", "review", "Experiment review: old: rejected", "r", done)
    research.note(conn, "recovery", "exploration", "Design gap: x", "e")
    open_ = research.note(conn, "recovery", "proposal", "Experiment proposal: new", "d")
    assert [r[0] for r in conn.execute(sql.group(1)).fetchall()] == [open_]


def test_lab_job_sends_the_methodologist_to_the_proposals() -> None:
    job = _LAB_JOB.read_text()
    assert "Experiment proposal" in job.split("## 3. Methodologist")[1].split("## 4.")[0]
    assert "all three queues" in job
