"""Foster's monotony and strain — the axis ACWR does not measure.

ACWR asks whether this week is bigger than the last few. Monotony asks whether
every day looks the same. They are different failure modes: an athlete can hold
a perfectly flat ACWR of 1.0 while training identically seven days a week, and
Foster's cohort suggests that sameness is itself a risk factor.

    session load = session RPE x duration      (Foster 2001)
    monotony     = mean(daily load) / SD(daily load)   over a 7-day window
    strain       = weekly load x monotony      (Foster 1998)

**Attribution matters here and is easy to get wrong.** The vault carries
`foster-2001-session-rpe-training-load`, which is session-RPE only. Monotony and
strain are Foster 1998, Med Sci Sports Exerc 30:1164-8 (PMID 9662690,
doi:10.1097/00005768-199807000-00023) — a different paper, in which illness
incidence tracked "individually identifiable training thresholds, mostly related
to the strain of training".

**On the 2.0 monotony threshold: Foster 1998 did not publish one.** The paper's
own framing is that the thresholds are individual. The widely-repeated 2.0
figure is downstream heuristic, so it ships here labelled as a heuristic
reference line rather than a validated cut-point, and the payload carries the
subject's own distribution so a personal threshold can eventually replace it.
Quoting 2.0 as "Foster's threshold" is the same class of error as attributing
FIB-4's MASLD cut-offs to Sterling.

Read-only. Nothing here gates anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

# Heuristic reference only — see the module docstring. NOT from Foster 1998.
_MONOTONY_HEURISTIC = 2.0

# A week needs at least this many training days for an SD to mean anything.
# With one session, SD across the week is dominated by the six zeros and
# monotony is an artefact of rest, not of sameness.
_MIN_TRAINING_DAYS = 2

# Fallback RPE when a set carries none, so a week of unrated sets still yields a
# load rather than silently vanishing. Deliberately mid-scale.
_ASSUMED_RPE = 7.0

# A week of IDENTICAL daily loads has an SD of exactly zero, so monotony is
# mean/0 — undefined, and infinitely monotonous. The first cut of this module
# guarded with `if sd > 0` and therefore dropped precisely the weeks the metric
# exists to catch: seven identical days scored as no data. Perfect uniformity is
# reported at this ceiling with `perfectly_uniform` set, never discarded.
# (Same failure shape as treating an SWC of 0.0 as missing in `noise_floor`.)
_UNIFORM_MONOTONY_CEILING = 99.0


@dataclass(frozen=True)
class Week:
    week_start: date
    load: float
    monotony: float
    strain: float
    training_days: int
    perfectly_uniform: bool = False

    def as_dict(self) -> dict:
        return {
            "week_start": self.week_start.isoformat(),
            "load": round(self.load, 1),
            "monotony": round(self.monotony, 2),
            "strain": round(self.strain, 1),
            "training_days": self.training_days,
            "above_heuristic": self.monotony > _MONOTONY_HEURISTIC,
            # True when every training day carried an identical load, so the
            # monotony figure is a floor-of-infinity, not a measurement.
            "perfectly_uniform": self.perfectly_uniform,
        }


def _daily_load(conn, since: str) -> dict[date, float]:
    """Session-RPE load per calendar day: sum of (volume-load x RPE/10)."""
    rows = conn.execute(
        """
        SELECT w.started_at::DATE d,
               SUM(s.weight_kg * s.reps * COALESCE(s.rpe, ?) / 10.0)
        FROM workouts w JOIN workout_sets s ON s.workout_id = w.id
        WHERE s.is_warmup = FALSE AND s.weight_kg > 0 AND s.reps > 0
          AND w.started_at::DATE >= ?
        GROUP BY 1
        """,
        [_ASSUMED_RPE, since],
    ).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def monotony_series(conn, weeks: int = 12) -> dict:
    """Weekly load, monotony and strain over the trailing `weeks`."""
    today = date.today()
    since = (today - timedelta(weeks=weeks + 1)).isoformat()
    by_day = _daily_load(conn, since)
    if not by_day:
        return {"weeks": [], "verdict": "no data"}

    start = min(by_day)
    # Anchor to Monday so weeks are comparable and stable across runs.
    start -= timedelta(days=start.weekday())

    out: list[Week] = []
    cursor = start
    while cursor <= today:
        window = [by_day.get(cursor + timedelta(days=i), 0.0) for i in range(7)]
        n_training = sum(1 for x in window if x > 0)
        if n_training >= _MIN_TRAINING_DAYS:
            m, sd = mean(window), pstdev(window)
            uniform = sd == 0
            mono = _UNIFORM_MONOTONY_CEILING if uniform else m / sd
            out.append(
                Week(cursor, sum(window), mono, sum(window) * mono, n_training, uniform)
            )
        cursor += timedelta(days=7)

    recent = out[-weeks:]
    if not recent:
        return {"weeks": [], "verdict": "insufficient"}

    monos = [w.monotony for w in recent]
    peak = max(recent, key=lambda w: w.strain)
    return {
        "weeks": [w.as_dict() for w in recent],
        "latest": recent[-1].as_dict(),
        "monotony_median": round(sorted(monos)[len(monos) // 2], 2),
        "monotony_max": round(max(monos), 2),
        "peak_strain_week": peak.as_dict(),
        "heuristic_reference": _MONOTONY_HEURISTIC,
        "weeks_above_heuristic": sum(1 for w in recent if w.monotony > _MONOTONY_HEURISTIC),
        "verdict": ("varied" if max(monos) <= _MONOTONY_HEURISTIC else "monotonous weeks present"),
        "attribution": (
            "Monotony and strain: Foster 1998, Med Sci Sports Exerc 30:1164-8 "
            "(doi:10.1097/00005768-199807000-00023). Session-RPE load: Foster 2001. "
            "The 2.0 reference line is a downstream heuristic — Foster's own "
            "thresholds were individually identified, not published as a universal "
            "cut-point."
        ),
    }
