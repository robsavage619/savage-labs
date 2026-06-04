from __future__ import annotations

"""Per-muscle weekly training volume — the corrected single source of truth.

Replaces two earlier broken implementations:
  * ``training.py:get_muscle_volume`` joined anatomical actuals against
    movement-pattern targets that never matched (see migration 0040).
  * ``mesocycle.py:_actual_sets_this_week`` keyword-matched exercise names and
    mis-bucketed direct arm work into "pull", so biceps/glutes were invisible.

Volume is counted from ``exercise_muscle_map``: a working set gives 1.0 credit to
its ``primary_muscle`` and ``SECONDARY_CREDIT`` (0.5) to each ``secondary_muscle``
— the Renaissance Periodization indirect-volume convention. Warmups and
zero-load/zero-rep sets are excluded.
"""

import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

log = logging.getLogger(__name__)

# Indirect (secondary) volume credit per set. Genuine synergists worked hard by a
# compound (glutes/hams off a squat) get the standard 0.5; the elbow flexors/
# extensors get less, because they're rarely the limiting factor on a press/row
# and over-crediting them off compounds suppresses the direct arm volume the
# biceps-emphasis goal wants (panel review M1).
SECONDARY_CREDIT = 0.5
ARM_SECONDARY_CREDIT = 0.3
_ARM_MUSCLES = ("biceps", "triceps", "forearms")

# Hypertrophy stimulating-rep window. Sets outside 5–30 reps don't count toward
# the MEV/MAV/MRV landmarks, which are calibrated to this range (panel review M1).
# (No RIR gate: Hevy floors its RPE picker at 6 — i.e. RIR ≤ 4 — so every logged
# Hevy set is already inside the stimulating range by construction.)
_REP_MIN, _REP_MAX = 5, 30
_STIMULATING = f"ws.reps BETWEEN {_REP_MIN} AND {_REP_MAX}"


@dataclass
class MuscleVolume:
    """A muscle's actual weekly volume against its MEV/MAV/MRV landmarks."""

    muscle: str
    actual_sets: float
    mev: int | None
    mav: int | None
    mrv: int | None
    status: str  # 'below MEV' | 'in range' | 'approaching MRV' | 'over MRV' | 'untargeted'


def weekly_muscle_volume(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> dict[str, float]:
    """Credited working sets per muscle for the [week_start, week_end) window.

    Primary muscle gets 1.0 per set; each secondary gets ``ARM_SECONDARY_CREDIT``
    for elbow flexors/extensors else ``SECONDARY_CREDIT``. Only warmup-free,
    loaded sets inside the 5–30 rep stimulating window count. Exercises absent
    from ``exercise_muscle_map`` contribute nothing (see :func:`unmapped_exercises`).

    Args:
        conn: Open DuckDB connection.
        week_start: Inclusive start of the window.
        week_end: Exclusive end; defaults to ``week_start + 7 days``.

    Returns:
        Mapping of canonical muscle name → credited set count (float).
    """
    end = week_end or week_start + timedelta(days=7)
    params = [week_start.isoformat(), end.isoformat()]

    primary = conn.execute(
        f"""
        SELECT m.primary_muscle, COUNT(*)::DOUBLE AS sets
        FROM workout_sets_dedup ws
        JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
        GROUP BY m.primary_muscle
        """,
        params,
    ).fetchall()

    secondary = conn.execute(
        f"""
        SELECT u.sec AS muscle,
               SUM(CASE WHEN u.sec IN ('biceps', 'triceps', 'forearms')
                        THEN {ARM_SECONDARY_CREDIT} ELSE {SECONDARY_CREDIT} END) AS credit
        FROM workout_sets_dedup ws
        JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        CROSS JOIN UNNEST(m.secondary_muscles) AS u(sec)
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
        GROUP BY u.sec
        """,
        params,
    ).fetchall()

    totals: dict[str, float] = defaultdict(float)
    for muscle, sets in primary:
        totals[muscle] += float(sets)
    for muscle, credit in secondary:
        totals[muscle] += float(credit)
    return dict(totals)


def unmapped_exercises(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> list[str]:
    """Exercises trained in the window with no ``exercise_muscle_map`` entry."""
    end = week_end or week_start + timedelta(days=7)
    rows = conn.execute(
        """
        SELECT DISTINCT ws.exercise
        FROM workout_sets_dedup ws
        LEFT JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND ws.reps > 0
          AND m.exercise_name IS NULL
        ORDER BY ws.exercise
        """,
        [week_start.isoformat(), end.isoformat()],
    ).fetchall()
    return [r[0] for r in rows]


def _status(actual: float, mev: int | None, mav: int | None, mrv: int | None) -> str:
    if mev is None or mav is None or mrv is None:
        return "untargeted"
    if actual < mev:
        return "below MEV"
    if actual < mav:
        return "in range"
    if actual <= mrv:
        return "approaching MRV"
    return "over MRV"


def build_muscle_report(
    actuals: dict[str, float],
    targets: Mapping[str, object],
) -> list[MuscleVolume]:
    """Combine actual volume with MEV/MAV/MRV targets into a per-muscle report.

    Pure function (no DB) for testability. ``targets`` maps muscle →
    ``VolumeTarget`` (from :func:`shc.training.mesocycle.volume_targets`); only
    its ``mev``/``mav``/``mrv`` attributes are read.

    Returns:
        One :class:`MuscleVolume` per muscle in the union of actuals and targets,
        sorted by muscle name.
    """
    muscles = sorted(set(actuals) | set(targets))
    report: list[MuscleVolume] = []
    for m in muscles:
        t = targets.get(m)
        mev = getattr(t, "mev", None)
        mav = getattr(t, "mav", None)
        mrv = getattr(t, "mrv", None)
        actual = round(actuals.get(m, 0.0), 1)
        report.append(MuscleVolume(m, actual, mev, mav, mrv, _status(actual, mev, mav, mrv)))
    return report
