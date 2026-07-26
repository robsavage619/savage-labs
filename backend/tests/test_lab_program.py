from __future__ import annotations

# Regression suite for the standing research program's lifecycle.
#
# Three defects, all in how the program handled an ANSWERED question:
#   1. /api/lab/findings filtered on `enabled = TRUE`, and rotate_if_stable
#      disables a question at exactly the moment it reaches a stable definitive
#      verdict — so the panel could only ever show unanswered questions. Nine
#      resolved hypotheses, including both CONFIRMED findings, were invisible.
#   2. run_all skipped retired questions forever, freezing every answer at
#      whatever the data said the day it stabilised.
#   3. _apply_fdr's denominator was "whatever ran this cycle", which shrank as
#      questions retired (to m=3, against a docstring claiming ~15), quietly
#      loosening the correction over time.
import uuid
from datetime import datetime, timedelta

import duckdb

from shc.lab import (
    _REVERIFY_AFTER_DAYS,
    LabFinding,
    _apply_fdr,
    _catalogue_size,
    _questions_to_run,
    reverify_retired,
)


def _add_question(
    conn: duckdb.DuckDBPyConnection,
    qid: str,
    *,
    enabled: bool = True,
    retired: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO lab_questions
            (id, title, hypothesis, exposure, outcome, test_type, window_days,
             min_n, threshold, direction, vault_ref, enabled, retired_at)
        VALUES ($id, $t, $h, 'x', 'y', 'paired_t', 90, 10, 1.0, 'positive', NULL, $en, $ret)
        """,
        {
            "id": qid,
            "t": f"title {qid}",
            "h": f"hypothesis {qid}",
            "en": enabled,
            "ret": datetime(2026, 6, 1) if retired else None,
        },
    )


def _add_finding(
    conn: duckdb.DuckDBPyConnection,
    qid: str,
    verdict: str,
    *,
    run_at: datetime,
    n: int = 50,
) -> None:
    conn.execute(
        """
        INSERT INTO lab_findings
            (id, question_id, run_at, n, effect_size, effect_unit, p_value, verdict, summary, evidence)
        VALUES ($id, $qid, $rt, $n, 1.0, 'ms', 0.02, $v, 's', '[]')
        """,
        {"id": str(uuid.uuid4()), "qid": qid, "rt": run_at, "n": n, "v": verdict},
    )


def _finding(qid: str, verdict: str, p: float | None) -> LabFinding:
    return LabFinding(qid, 50, 1.0, "ms", p, verdict, "summary", [])


# ── the FDR denominator ──────────────────────────────────────────────────────


def test_fdr_denominator_is_the_catalogue_not_the_run():
    """The same p-value must not change verdict because a sibling retired.

    Two identical runs, one with three live questions and one with a single
    survivor. Under the old run-scoped denominator the survivor's p=0.030 was
    corrected against m=1 (critical value 0.10) and stayed CONFIRMED; against
    the real 15-question catalogue it cannot.
    """
    lone = [_finding("a", "confirmed", 0.030)]
    _apply_fdr(lone, family_size=15)
    assert lone[0].verdict == "inconclusive"
    assert "15 simultaneous hypotheses" in lone[0].summary

    # Same finding, same catalogue — the presence of other live questions must
    # not change the answer.
    with_siblings = [
        _finding("a", "confirmed", 0.030),
        _finding("b", "inconclusive", 0.4),
        _finding("c", "inconclusive", 0.7),
    ]
    _apply_fdr(with_siblings, family_size=15)
    assert with_siblings[0].verdict == "inconclusive"


def test_fdr_family_size_is_a_floor_never_shrinks_below_the_run():
    """A family_size smaller than the run can't loosen the correction.

    p=0.04 alone against m=2 would clear the rank-1 critical value (0.05) and
    stay confirmed; run alongside nine other tests it must be corrected at m=10
    (critical 0.01) regardless of what the caller passes.
    """
    findings = [_finding("strong", "confirmed", 0.04)] + [
        _finding(f"q{i}", "inconclusive", 0.9) for i in range(9)
    ]
    _apply_fdr(findings, family_size=2)
    assert findings[0].verdict == "inconclusive"


def test_fdr_still_confirms_a_genuinely_strong_result():
    """The correction must not be a blanket veto — a small enough p survives."""
    findings = [_finding("a", "confirmed", 0.002)] + [
        _finding(f"q{i}", "inconclusive", 0.5) for i in range(5)
    ]
    _apply_fdr(findings, family_size=15)
    assert findings[0].verdict == "confirmed"


def test_catalogue_size_counts_retired_questions(conn):
    """Retired questions stay in the multiple-comparisons family — they were
    tested against the same dataset, and dropping them is what let the
    denominator drift down to 3."""
    baseline = _catalogue_size(conn)  # migrations seed the catalogue
    _add_question(conn, "live_one")
    _add_question(conn, "answered_one", enabled=False, retired=True)

    assert _catalogue_size(conn) == baseline + 2


# ── re-verification of answered questions ────────────────────────────────────


def test_stale_retired_question_is_rerun(conn):
    """An answer older than the re-verify window goes back through the runner."""
    _add_question(conn, "stale", enabled=False, retired=True)
    _add_finding(
        conn,
        "stale",
        "confirmed",
        run_at=datetime.now() - timedelta(days=_REVERIFY_AFTER_DAYS + 5),
    )

    ids = [r[0] for r in _questions_to_run(conn)]

    assert "stale" in ids


def test_recently_rechecked_retired_question_is_not_rerun(conn):
    _add_question(conn, "fresh", enabled=False, retired=True)
    _add_finding(conn, "fresh", "confirmed", run_at=datetime.now() - timedelta(days=2))

    ids = [r[0] for r in _questions_to_run(conn)]

    assert "fresh" not in ids


def test_enabled_questions_always_run(conn):
    _add_question(conn, "open_one")
    assert "open_one" in [r[0] for r in _questions_to_run(conn)]


def test_reverification_that_disagrees_reopens_the_question(conn):
    """A confirmed effect that stops holding goes back under test."""
    _add_question(conn, "flipped", enabled=False, retired=True)
    _add_finding(conn, "flipped", "confirmed", run_at=datetime(2026, 6, 1))
    _add_finding(conn, "flipped", "inconclusive", run_at=datetime(2026, 7, 20))

    reopened = reverify_retired(conn, [_finding("flipped", "inconclusive", 0.4)])

    assert reopened == ["flipped"]
    row = conn.execute(
        "SELECT enabled, retired_at FROM lab_questions WHERE id = 'flipped'"
    ).fetchone()
    assert row[0] is True
    assert row[1] is None


def test_reverification_that_agrees_leaves_it_retired(conn):
    _add_question(conn, "holds", enabled=False, retired=True)
    _add_finding(conn, "holds", "confirmed", run_at=datetime(2026, 6, 1))
    _add_finding(conn, "holds", "confirmed", run_at=datetime(2026, 7, 20))

    reopened = reverify_retired(conn, [_finding("holds", "confirmed", 0.01)])

    assert reopened == []
    assert (
        conn.execute("SELECT enabled FROM lab_questions WHERE id = 'holds'").fetchone()[0] is False
    )


def test_a_runner_crash_never_reopens_a_question(conn):
    """'error' means the hypothesis was not tested — it is not a disagreement."""
    _add_question(conn, "crashed", enabled=False, retired=True)
    _add_finding(conn, "crashed", "confirmed", run_at=datetime(2026, 6, 1))
    _add_finding(conn, "crashed", "error", run_at=datetime(2026, 7, 20))

    assert reverify_retired(conn, [_finding("crashed", "error", None)]) == []
    assert (
        conn.execute("SELECT enabled FROM lab_questions WHERE id = 'crashed'").fetchone()[0]
        is False
    )


def test_open_questions_are_never_reopened(conn):
    """reverify only governs answered questions; live ones are rotate's business."""
    _add_question(conn, "live")
    _add_finding(conn, "live", "confirmed", run_at=datetime(2026, 6, 1))
    _add_finding(conn, "live", "refuted", run_at=datetime(2026, 7, 20))

    assert reverify_retired(conn, [_finding("live", "refuted", 0.4)]) == []
