"""A crashed lab runner must surface as ERROR, never as a real finding.

An exception means the hypothesis was never tested. Classifying it as
'inconclusive' let a bug masquerade as a null result in the workout context
(and made it eligible for promotion to an n-of-1 experiment).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc import lab
from shc.ai.lab_findings import lab_findings_section


def _question(conn, qid: str = "boom_q") -> None:
    conn.execute(
        "INSERT INTO lab_questions (id, title, hypothesis, exposure, outcome, "
        "test_type, window_days, min_n, threshold, direction, vault_ref, enabled) "
        "VALUES (?, 'Exploding hypothesis', 'hyp', 'x', 'y', 'rate', 90, 3, 0.4, 'up', NULL, TRUE)",
        [qid],
    )


def test_raising_runner_is_error_not_inconclusive(conn, monkeypatch) -> None:
    _question(conn)

    def _boom(_conn, _q):
        raise TypeError("dictionary update sequence element #0 has length 3; 2 is required")

    monkeypatch.setitem(lab._RUNNERS, "boom_q", _boom)
    (finding,) = [f for f in lab.run_all(conn) if f.question_id == "boom_q"]

    assert finding.verdict == "error"
    assert finding.verdict != "inconclusive"
    assert "TypeError" in finding.summary


def test_error_findings_are_not_experiment_candidates(conn, monkeypatch) -> None:
    """selflab.suggest_experiments promotes inconclusive/insufficient findings.

    A crashed runner must not be nominated as a study candidate.
    """
    _question(conn)
    monkeypatch.setitem(lab._RUNNERS, "boom_q", lambda c, q: 1 / 0)
    lab.persist(conn, lab.run_all(conn))

    eligible = conn.execute(
        "SELECT question_id FROM lab_findings WHERE verdict IN ('inconclusive', 'insufficient')"
    ).fetchall()
    assert ("boom_q",) not in eligible


def test_error_renders_visibly_and_without_fake_stats(conn, monkeypatch) -> None:
    _question(conn)
    monkeypatch.setitem(lab._RUNNERS, "boom_q", lambda c, q: 1 / 0)
    lab.persist(conn, lab.run_all(conn))

    section = lab_findings_section(conn)
    (error_line,) = [ln for ln in section.splitlines() if "Exploding hypothesis" in ln]

    assert "ERROR" in error_line
    assert "INCONCLUSIVE" not in error_line
    # n=0 on the error line would read as "the test ran and found no data".
    # (Genuine INSUFFICIENT rows legitimately render n=0, hence the line scope.)
    assert "(n=0)" not in error_line
    # Errors sort to the top so a broken runner can't hide mid-list.
    assert section.splitlines().index(error_line) == 2


def test_rhr_trend_runner_handles_three_column_rows(conn) -> None:
    """Regression: the runner selects (date, hrv, rhr) but built a dict from
    the raw 3-tuples, which raises before any result can be computed.
    """
    start = date.today() - timedelta(days=80)
    for i in range(80):
        day = start + timedelta(days=i)
        # Rising RHR in the back half so trigger branches are actually reached.
        rhr = 52 + (6 if i > 40 else 0)
        conn.execute(
            "INSERT INTO recovery (id, source, date, hrv, rhr, content_hash) "
            "VALUES (?, 'test', ?, ?, ?, ?)",
            [f"r{i}", day.isoformat(), 60.0 - (i % 7), rhr, f"h{i}"],
        )

    q = {
        "id": "rhr_trend_hrv_drop",
        "title": "t",
        "hypothesis": "h",
        "exposure": "x",
        "outcome": "y",
        "test_type": "rate",
        "window_days": 120,
        "min_n": 3,
        "threshold": 0.4,
        "direction": "up",
        "vault_ref": None,
    }
    finding = lab._run_rhr_trend_hrv_drop(conn, q)

    assert finding.verdict != "error"
    assert finding.verdict in {"confirmed", "refuted", "inconclusive", "insufficient"}


@pytest.mark.parametrize("qid", sorted(lab._RUNNERS))
def test_every_runner_survives_an_empty_database(conn, qid: str) -> None:
    """No runner may raise on a cold database — that path is all-or-nothing."""
    q = {
        "id": qid,
        "title": "t",
        "hypothesis": "h",
        "exposure": "x",
        "outcome": "y",
        "test_type": "rate",
        "window_days": 90,
        "min_n": 3,
        "threshold": 0.4,
        "direction": "up",
        "vault_ref": None,
    }
    finding = lab._RUNNERS[qid](conn, q)
    assert finding.verdict in {"confirmed", "refuted", "inconclusive", "insufficient"}
