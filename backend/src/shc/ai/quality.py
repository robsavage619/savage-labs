from __future__ import annotations

"""Output-quality metrics for the data→LLM wiring.

Schema/gate validation (``validate_plan``) proves a returned plan is *legal*.
These metrics measure whether the plans are *good* over time — deterministic,
no LLM calls, read straight from ``plan_adherence`` (prescribed vs actual RPE
and completion) which the scheduler already populates nightly.

Three signals:
    rpe_calibration_error    — are prescribed RPEs matching what got delivered?
    adherence_completion_trend — are plans actually being completed?
    citation_validity_rate   — are stored plans grounding claims in real notes?

All functions degrade gracefully (return ``None`` / empty) when the underlying
table or column is missing, rather than fabricating SQL against a schema that
isn't there.
"""

import json
import logging
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)


def _cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def rpe_calibration_error(conn: Any, days: int = 14) -> float | None:
    """Mean absolute (avg_rpe_actual − avg_rpe_target) over the window.

    Lower is better: prescriptions land at the effort actually delivered. A
    persistent positive bias means plans under-prescribe; negative means they
    over-prescribe. Returns ``None`` when no adherence row in the window has
    both an actual and target RPE.

    Args:
        conn: Open DuckDB connection.
        days: Look-back window in days (default 14).
    """
    try:
        row = conn.execute(
            """
            SELECT AVG(ABS(avg_rpe_actual - avg_rpe_target))
            FROM plan_adherence
            WHERE date >= $cutoff
              AND avg_rpe_actual IS NOT NULL
              AND avg_rpe_target IS NOT NULL
            """,
            {"cutoff": _cutoff(days)},
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 — missing table/column → no metric, not a crash
        log.debug("rpe_calibration_error skipped: %s", exc)
        return None
    return round(float(row[0]), 2) if row and row[0] is not None else None


def adherence_completion_trend(conn: Any, days: int = 30) -> dict[str, Any]:
    """Rolling completion-pct stats over the window.

    Returns a dict with ``latest`` (most recent completion_pct), ``mean``
    (window average), ``n`` (rows counted), and ``direction`` (``improving`` /
    ``declining`` / ``flat`` / ``insufficient``) computed by comparing the first
    and second half of the window. All values are ``None`` when no data exists.

    Args:
        conn: Open DuckDB connection.
        days: Look-back window in days (default 30).
    """
    empty: dict[str, Any] = {"latest": None, "mean": None, "n": 0, "direction": "insufficient"}
    try:
        rows = conn.execute(
            """
            SELECT date, completion_pct
            FROM plan_adherence
            WHERE date >= $cutoff
              AND completion_pct IS NOT NULL
            ORDER BY date
            """,
            {"cutoff": _cutoff(days)},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — degrade, don't crash
        log.debug("adherence_completion_trend skipped: %s", exc)
        return empty
    if not rows:
        return empty

    values = [float(r[1]) for r in rows]
    latest = values[-1]
    mean = sum(values) / len(values)
    direction = "insufficient"
    if len(values) >= 4:
        half = len(values) // 2
        first = sum(values[:half]) / half
        second = sum(values[half:]) / (len(values) - half)
        delta = second - first
        direction = "improving" if delta > 5 else "declining" if delta < -5 else "flat"
    return {
        "latest": round(latest, 1),
        "mean": round(mean, 1),
        "n": len(values),
        "direction": direction,
    }


def citation_validity_rate(conn: Any, allowed: set[str], days: int = 90) -> float | None:
    """Fraction of stored plans whose vault_insights cite only real notes.

    For each plan in the window, extracts ``*.md`` filenames from its
    vault_insights and checks them against ``allowed`` (the real vault filename
    set from ``shc.ai.vault.valid_citation_filenames``). A plan counts as valid
    if it cites at least one real note and cites no unknown note. Returns the
    valid fraction in [0, 1], or ``None`` if there are no plans or ``allowed``
    is empty (vault unavailable).

    Args:
        conn: Open DuckDB connection.
        allowed: Set of real vault note filenames.
        days: Look-back window in days (default 90).
    """
    if not allowed:
        return None
    from shc.ai.workout_planner import _CITATION_RE

    try:
        rows = conn.execute(
            """
            SELECT plan_json
            FROM workout_plans
            WHERE date >= $cutoff
            """,
            {"cutoff": _cutoff(days)},
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — degrade, don't crash
        log.debug("citation_validity_rate skipped: %s", exc)
        return None
    if not rows:
        return None

    valid = 0
    total = 0
    for (plan_json,) in rows:
        try:
            plan = json.loads(plan_json)
        except (json.JSONDecodeError, TypeError):
            continue
        total += 1
        cited: set[str] = set()
        for insight in plan.get("vault_insights") or []:
            text = insight if isinstance(insight, str) else str(insight.get("source", ""))
            cited.update(m.group(1) for m in _CITATION_RE.finditer(text))
        if cited and not (cited - allowed):
            valid += 1
    return round(valid / total, 3) if total else None
