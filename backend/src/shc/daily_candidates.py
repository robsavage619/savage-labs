"""First daily-lane experiment candidates, sized by the lab's own placebo gate (WP 2.6).

Three proposals, none registered here. `size_candidates` runs `selflab.placebo_gate` on
a connection's own history, so the numbers are the registration gate's numbers; the
payload is the exact body for ``POST /api/experiments``. Rob picks one (decision D2) and
approves registration himself.

Run read-only against a copy of the history:

    python -m shc.daily_candidates /path/to/copy.duckdb
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import duckdb

from shc import selflab


@dataclass(frozen=True)
class Candidate:
    slug: str
    hypothesis: str
    manipulated: str
    condition_a: str
    condition_b: str
    outcome_metric: str
    outcome_direction: str
    min_effect: float
    prior_source: str

    def payload(self) -> dict:
        """Body for ``POST /api/experiments``; queued so it waits for a free daily lane."""
        return {
            "slug": self.slug,
            "hypothesis": self.hypothesis,
            "manipulated": self.manipulated,
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "outcome_metric": self.outcome_metric,
            "outcome_direction": self.outcome_direction,
            "min_effect": self.min_effect,
            "notes": f"Prior: {self.prior_source}. Measures around routine only; no medicine "
            "or its timing is changed.",
            "queued": True,
        }


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        slug="last-meal-3h-rhr",
        hypothesis="Finishing the last meal at least 3 hours before bed lowers next-morning "
        "resting heart rate.",
        manipulated="last_meal_timing",
        condition_a="Usual evening meal timing",
        condition_b="Last meal finished at least 3 hours before bed",
        outcome_metric="rhr_next_morning",
        outcome_direction="lower_better",
        min_effect=2.5,
        prior_source="winter-2017-ch7-circadian-rhythms (meal timing as a circadian anchor)",
    ),
    Candidate(
        slug="caffeine-cutoff-1400-deep-sleep",
        hypothesis="No caffeine after 14:00 raises that night's deep sleep.",
        manipulated="caffeine_cutoff",
        condition_a="Usual caffeine timing",
        condition_b="No caffeine after 14:00",
        outcome_metric="deep_sleep_min",
        outcome_direction="higher_better",
        min_effect=12.0,
        prior_source="guest-2021-issn-caffeine (within ~6 h of bed impairs sleep architecture)",
    ),
    Candidate(
        slug="evening-light-dim-sleep-efficiency",
        hypothesis="Dim lights and no screens for the hour before bed raise sleep efficiency.",
        manipulated="evening_light",
        condition_a="Usual evening light and screens",
        condition_b="Dim lights and no screens for the last 60 minutes before bed",
        outcome_metric="sleep_efficiency_pct",
        outcome_direction="higher_better",
        min_effect=2.5,
        prior_source="circadian-rhythm; bijlenga-2019-circadian-adhd (light drives phase)",
    ),
)


def size_candidates(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Gate numbers per candidate, from the connection's own history.

    Each row has the candidate's slug and outcome plus the gate's ``sd``,
    ``needed_per_arm``, ``days_to_answer``, ``detectable_120d`` and ``false_fire_rate``,
    ``weeks_to_verdict``, and ``passes`` (the registration gate would accept it).
    ``gate`` is None when there are fewer than 10 nights of history.
    """
    out = []
    for c in CANDIDATES:
        gate = selflab.placebo_gate(
            conn,
            slug=c.slug,
            outcome_metric=c.outcome_metric,
            min_effect=c.min_effect,
            design="randomized_alternating",
        )
        days = gate["days_to_answer"] if gate else None
        out.append(
            {
                "slug": c.slug,
                "outcome_metric": c.outcome_metric,
                "min_effect": c.min_effect,
                "gate": gate,
                "weeks_to_verdict": round(days / 7, 1) if days else None,
                "passes": bool(
                    gate
                    and days
                    and days <= selflab.MAX_DAYS_TO_ANSWER
                    and gate["false_fire_rate"] <= 2 * selflab._ALPHA
                ),
            }
        )
    return out


def main(argv: list[str]) -> int:
    conn = duckdb.connect(argv[0], read_only=True)
    try:
        for row in size_candidates(conn):
            g = row["gate"] or {}
            print(
                f"{row['slug']}: passes={row['passes']} weeks={row['weeks_to_verdict']} "
                f"needed/arm={g.get('needed_per_arm')} detectable_120d={g.get('detectable_120d')} "
                f"false_fire={g.get('false_fire_rate')}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
