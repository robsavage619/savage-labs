from __future__ import annotations

"""Inject pre-registered hypothesis verdicts into briefing / workout context.

Queries lab_findings for the most recent run per question and renders a concise
section that tells Claude what has been statistically confirmed or refuted on
Rob's own data — so interpretations are grounded in personal findings, not just
population-level assumptions.
"""

import logging

log = logging.getLogger(__name__)

_VERDICT_TAG = {
    "confirmed": "CONFIRMED",
    "refuted": "REFUTED",
    "inconclusive": "INCONCLUSIVE",
    "insufficient": "INSUFFICIENT DATA",
    "error": "ERROR — RUNNER FAILED",
}


def lab_findings_section(conn) -> str:
    """Return a context block with the latest verdict for each enabled question.

    Returns an empty string if the lab_questions table doesn't exist yet or has
    no rows, so callers don't need to guard.
    """
    try:
        rows = conn.execute(
            """
            SELECT
                q.title,
                q.hypothesis,
                f.verdict,
                f.effect_size,
                f.effect_unit,
                f.p_value,
                f.n,
                f.summary
            FROM lab_questions q
            LEFT JOIN (
                SELECT DISTINCT ON (question_id)
                    question_id, verdict, effect_size, effect_unit,
                    p_value, n, summary
                FROM lab_findings
                ORDER BY question_id, run_at DESC
            ) f ON f.question_id = q.id
            WHERE q.enabled = TRUE
            ORDER BY
                CASE f.verdict
                    WHEN 'error'        THEN 0
                    WHEN 'confirmed'    THEN 1
                    WHEN 'refuted'      THEN 2
                    WHEN 'inconclusive' THEN 3
                    ELSE 4
                END,
                q.id
            """
        ).fetchall()
    except Exception as exc:
        log.debug("lab_findings_section skipped: %s", exc)
        return ""

    if not rows:
        return ""

    lines = [
        "## YOUR PERSONAL LAB FINDINGS",
        "Pre-registered hypotheses tested against your own data. "
        "These override population assumptions — a REFUTED finding means "
        "the effect doesn't hold for you personally. An ERROR entry is a "
        "broken runner, not a result: draw no conclusion from it.",
    ]

    for title, hypothesis, verdict, effect, unit, pval, n, summary in rows:
        if verdict is None:
            tag = "NOT YET RUN"
            detail = hypothesis
        elif verdict == "error":
            # No stats suffix: the runner crashed, so n/p/effect describe
            # nothing. "(n=0)" here would read as a test that found no data.
            tag = _VERDICT_TAG["error"]
            detail = f"{summary or 'runner failed'} Treat this hypothesis as untested."
        else:
            tag = _VERDICT_TAG.get(verdict, verdict.upper())
            parts: list[str] = []
            if effect is not None and unit:
                sign = "+" if effect > 0 else ""
                parts.append(f"effect {sign}{effect:.2f}{unit}")
            if n is not None:
                parts.append(f"n={n}")
            if pval is not None:
                parts.append(f"p={pval:.3f}")
            detail = summary or hypothesis
            if parts:
                detail += f" ({', '.join(parts)})"

        lines.append(f"- [{tag}] {title}: {detail}")

    return "\n".join(lines)
