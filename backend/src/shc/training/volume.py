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
_REP_MIN, _REP_MAX = 5, 30
_STIMULATING = f"ws.reps BETWEEN {_REP_MIN} AND {_REP_MAX}"

# Per-set RIR/RPE gate (#23). A set only drives hypertrophy when taken close
# enough to failure; the MEV/MAV/MRV landmarks assume working sets at roughly
# RIR ≤ 4 (RPE ≥ 6). Hevy ingests a per-set ``rpe`` value, so when it's present
# we USE it instead of assuming every loaded set is stimulating:
#   * RPE ≥ _STIMULATING_RPE → full credit.
#   * RPE <  _STIMULATING_RPE → not stimulating, contributes 0 (a back-off /
#     feeder single Rob explicitly graded easy shouldn't count toward MRV).
# When ``rpe`` is NULL we fall back to the prior assumption (count it) rather than
# silently zeroing the set — Rob logs RPE on <2% of Hevy sets and never on the
# Fitbod history, so a hard NULL-excludes gate would erase ~99% of real volume.
# The size of that assumption is surfaced by :func:`rpe_coverage` so it can't
# hide. Threshold matches Hevy's RPE picker floor of 6 (RIR ≈ 4).
_STIMULATING_RPE = 6.0
_RPE_GATE = f"(ws.rpe IS NULL OR ws.rpe >= {_STIMULATING_RPE})"


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
    for elbow flexors/extensors else ``SECONDARY_CREDIT``. A set counts only when
    it is warmup-free, loaded, inside the 5–30 rep stimulating window, and passes
    the per-set RIR gate (#23): a logged ``rpe`` below ``_STIMULATING_RPE`` is
    excluded as non-stimulating, while a NULL ``rpe`` is assumed stimulating (see
    :func:`rpe_coverage` for how large that assumption currently is). Exercises
    absent from ``exercise_muscle_map`` contribute nothing (see
    :func:`unmapped_exercises`).

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
          AND {_RPE_GATE}
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
          AND {_RPE_GATE}
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


def weekly_region_volume(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> dict[str, dict[str, float]]:
    """Credited working sets per muscle HEAD/REGION for the window.

    The head-level counterpart to :func:`weekly_muscle_volume`: it credits each
    stimulating working set to the specific region(s) the ``exercise_science``
    layer says the movement trains — so a Hammer Curl credits ``biceps/brachialis``
    AND ``forearms/brachioradialis``, not just "biceps". This is what lets the
    selector see WHICH head got stimulus and steer volume toward a neglected one
    (e.g. long-head trained six sets, brachialis zero) instead of repeating the
    same movement blind to head balance.

    Only the ~curated exercises carry region rows, so this is a coverage SIGNAL
    over the science-mapped movements, not a total-volume ledger; muscles/heads
    with no curated movement simply don't appear. Same warmup/load/rep/RPE gates
    as :func:`weekly_muscle_volume` so the two are directly comparable.

    Returns:
        ``{muscle: {region: credited_sets}}`` — one full set of credit per
        (muscle, region) science row an exercise matches.
    """
    end = week_end or week_start + timedelta(days=7)
    rows = conn.execute(
        f"""
        SELECT s.muscle, s.region, COUNT(*)::DOUBLE AS sets
        FROM workout_sets_dedup ws
        JOIN exercise_science s ON ws.exercise = s.exercise_name
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
          AND {_RPE_GATE}
        GROUP BY s.muscle, s.region
        """,
        [week_start.isoformat(), end.isoformat()],
    ).fetchall()
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for muscle, region, sets in rows:
        out[muscle][region or muscle] = float(sets)
    return {m: dict(r) for m, r in out.items()}


@dataclass
class RpeCoverage:
    """How much of the window's volume rests on the NULL-RPE assumption (#23).

    ``assumed_sets`` are loaded, in-window sets counted *without* a logged RPE
    (treated as stimulating by assumption). ``graded_stimulating`` and
    ``graded_excluded`` are sets that carried a real RPE at/above and below the
    stimulating threshold respectively; the latter are the only sets the gate
    actually drops. A high ``assumed_pct`` means the RIR gate is mostly inert
    because Rob isn't logging RPE — surface it, don't hide it.
    """

    counted_sets: int
    assumed_sets: int
    graded_stimulating: int
    graded_excluded: int
    assumed_pct: float


def rpe_coverage(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> RpeCoverage:
    """Per-set RPE logging coverage over the mapped, in-window working sets.

    Makes the NULL-RPE assumption baked into :func:`weekly_muscle_volume` visible
    so a viewer can tell whether the RIR gate is doing real work or just passing
    everything through.

    Args:
        conn: Open DuckDB connection.
        week_start: Inclusive start of the window.
        week_end: Exclusive end; defaults to ``week_start + 7 days``.

    Returns:
        An :class:`RpeCoverage` summarising counted vs assumed vs graded sets.
    """
    end = week_end or week_start + timedelta(days=7)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE ws.rpe IS NULL)                       AS assumed,
            COUNT(*) FILTER (WHERE ws.rpe >= {_STIMULATING_RPE})         AS graded_ok,
            COUNT(*) FILTER (WHERE ws.rpe < {_STIMULATING_RPE})          AS graded_out
        FROM workout_sets_dedup ws
        JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
        """,
        [week_start.isoformat(), end.isoformat()],
    ).fetchone()
    assumed = int(row[0]) if row else 0
    graded_ok = int(row[1]) if row else 0
    graded_out = int(row[2]) if row else 0
    counted = assumed + graded_ok
    denom = counted or 1
    return RpeCoverage(
        counted_sets=counted,
        assumed_sets=assumed,
        graded_stimulating=graded_ok,
        graded_excluded=graded_out,
        assumed_pct=round(assumed / denom, 3),
    )


def unmapped_exercises(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> list[str]:
    """Exercises trained in the window with no ``exercise_muscle_map`` entry.

    Each such exercise silently contributes zero credited volume, so a
    miscategorised or freshly-renamed lift can quietly starve a muscle (#25). The
    specific names — with their dropped working-set counts — are logged at WARNING
    so the gap is visible; :func:`unmapped_exercise_sets` returns the same data
    structured for callers that want to surface it in a report.
    """
    detail = unmapped_exercise_sets(conn, week_start, week_end)
    if detail:
        named = ", ".join(f"{name} ({sets} sets)" for name, sets in detail)
        log.warning(
            "UNMAPPED EXERCISES (%d) contributing zero volume this window: %s",
            len(detail),
            named,
        )
    return [name for name, _ in detail]


def unmapped_exercise_sets(
    conn: duckdb.DuckDBPyConnection,
    week_start: date,
    week_end: date | None = None,
) -> list[tuple[str, int]]:
    """Unmapped in-window exercises with their dropped working-set counts.

    Returns ``(exercise_name, set_count)`` pairs, busiest first, for every
    loaded, non-warmup exercise in ``[week_start, week_end)`` that has no
    ``exercise_muscle_map`` row and therefore credits zero volume (#25).
    """
    end = week_end or week_start + timedelta(days=7)
    rows = conn.execute(
        """
        SELECT ws.exercise, COUNT(*)::INTEGER AS sets
        FROM workout_sets_dedup ws
        LEFT JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND ws.reps > 0
          AND m.exercise_name IS NULL
        GROUP BY ws.exercise
        ORDER BY sets DESC, ws.exercise
        """,
        [week_start.isoformat(), end.isoformat()],
    ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def muscle_weekly_volume_series(
    conn: duckdb.DuckDBPyConnection,
    muscle: str,
    lookback_weeks: int,
) -> list[tuple[str, float]]:
    """Per-week credited set count for a muscle over the last N weeks.

    Uses the same warmup/rep/RPE gates and primary+secondary credit rates as
    :func:`weekly_muscle_volume`, so fitted landmarks and live volume are on the
    same scale. Returns ``[(iso_week_start, credited_sets)]`` oldest-first.
    """
    rows = conn.execute(
        f"""
        WITH credited AS (
            SELECT
                date_trunc('week', ws.started_at)::DATE AS week_start,
                1.0 AS credit
            FROM workout_sets_dedup ws
            JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
            WHERE m.primary_muscle = ?
              AND ws.started_at::DATE >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
              AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
              AND {_RPE_GATE}
            UNION ALL
            SELECT
                date_trunc('week', ws.started_at)::DATE AS week_start,
                CASE WHEN u.sec IN ('biceps', 'triceps', 'forearms')
                     THEN {ARM_SECONDARY_CREDIT} ELSE {SECONDARY_CREDIT} END AS credit
            FROM workout_sets_dedup ws
            JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
            CROSS JOIN UNNEST(m.secondary_muscles) AS u(sec)
            WHERE u.sec = ?
              AND ws.started_at::DATE >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
              AND NOT ws.is_warmup AND ws.weight_kg > 0 AND {_STIMULATING}
              AND {_RPE_GATE}
        )
        SELECT week_start, SUM(credit) AS credited_sets
        FROM credited
        GROUP BY week_start
        ORDER BY week_start
        """,
        [muscle, str(lookback_weeks), muscle, str(lookback_weeks)],
    ).fetchall()
    return [(str(r[0]), float(r[1])) for r in rows]


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
