from __future__ import annotations

import hashlib
import statistics
from datetime import date, timedelta
from typing import Any

import duckdb

from shc.training.load_mechanics import effective_reps_sql, per_hand_sql

# Protocol, fixed in advance: lab notebook note "Biceps block switched to left arm
# against right arm: right 14 sets, left 8" (approved 2026-11-24). Do not edit.
SLUG = "biceps-volume-left-vs-right-2026-11"
EXERCISE = {
    "left": "Single Arm Dumbbell Curl (Left)",
    "right": "Single Arm Dumbbell Curl (Right)",
}
PLACEBO_WEEK = date(2026, 11, 30)  # Monday; both arms 8 sets
FIRST_DOSE_WEEK = date(2026, 12, 7)
LAST_WEEK = date(2027, 1, 25)  # Monday of the final week, ends Sun 2027-01-31
DELOAD_WEEK = date(2027, 1, 11)  # excluded from dose weeks and delivery
SCORED_WEEKS = (date(2027, 1, 18), date(2027, 1, 25))  # the last two dose weeks
HIGH_SETS_MIN = 13.0
LOW_SETS_RANGE = (7.0, 9.0)
SUPPORTED_MIN_CHANGE = 2.0
RULED_OUT_BELOW = 1.0
SD_MULTIPLE = 2.0


def high_arm(slug: str = SLUG) -> str:
    """The high-dose arm, fixed by sha256(slug) parity: even is left, odd is right."""
    return "left" if int(hashlib.sha256(slug.encode()).hexdigest(), 16) % 2 == 0 else "right"


HIGH_ARM = high_arm()


def _weeks() -> list[date]:
    n = (LAST_WEEK - PLACEBO_WEEK).days // 7
    return [PLACEBO_WEEK + timedelta(weeks=i) for i in range(n + 1)]


def _phase(week: date) -> str:
    if week == PLACEBO_WEEK:
        return "placebo"
    return "deload" if week == DELOAD_WEEK else "dose"


def _set_counts(conn: duckdb.DuckDBPyConnection) -> dict[tuple[date, str], int]:
    rows = conn.execute(
        """
        SELECT date_trunc('week', day_d)::DATE, exercise, COUNT(*)
        FROM workout_sets_dedup
        WHERE exercise IN (?, ?) AND NOT COALESCE(is_warmup, FALSE)
          AND day_d BETWEEN ? AND ?
        GROUP BY 1, 2
        """,
        [EXERCISE["left"], EXERCISE["right"], PLACEBO_WEEK, LAST_WEEK + timedelta(days=6)],
    ).fetchall()
    arm_of = {v: k for k, v in EXERCISE.items()}
    return {(wk, arm_of[ex]): int(n) for wk, ex, n in rows}


def _test_set_e1rm(conn: duckdb.DuckDBPyConnection) -> dict[date, dict[str, float]]:
    """Per day and arm, e1RM of the first non-warmup set (lowest set_idx)."""
    eff = effective_reps_sql("reps", "rpe")
    hand = per_hand_sql("weight_kg", "exercise", "day_d")
    rows = conn.execute(
        f"""
        SELECT day_d, exercise, ({hand}) * (1 + ({eff}) / 30.0)
        FROM (
            SELECT *, row_number() OVER (
                PARTITION BY day_d, exercise ORDER BY started_at, set_idx) AS rn
            FROM workout_sets_dedup
            WHERE exercise IN (?, ?) AND NOT COALESCE(is_warmup, FALSE)
              AND day_d BETWEEN ? AND ?
        )
        WHERE rn = 1 AND weight_kg > 0 AND reps > 0
        """,
        [EXERCISE["left"], EXERCISE["right"], PLACEBO_WEEK, LAST_WEEK + timedelta(days=6)],
    ).fetchall()
    arm_of = {v: k for k, v in EXERCISE.items()}
    out: dict[date, dict[str, float]] = {}
    for day, ex, e1rm in rows:
        out.setdefault(day, {})[arm_of[ex]] = float(e1rm)
    return out


def _gaps(tests: dict[date, dict[str, float]]) -> list[tuple[date, float]]:
    """Per-session gap%, right over left; sessions missing an arm are skipped."""
    return sorted(
        (d, 100.0 * (a["right"] / a["left"] - 1.0))
        for d, a in tests.items()
        if "left" in a and "right" in a
    )


def _mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def score(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict[str, Any]:
    """Score the left-against-right biceps experiment. Read-only and deterministic.

    Args:
        conn: A DuckDB connection (only read).
        today: Evaluation date; the single look happens after the window closes.

    Returns:
        Weekly table, placebo SD, change, delivery check, verdict and reason.
    """
    today = today or date.today()
    counts = _set_counts(conn)
    gaps = _gaps(_test_set_e1rm(conn))

    def week_of(d: date) -> date:
        return d - timedelta(days=d.weekday())

    by_week: dict[date, list[float]] = {}
    for d, g in gaps:
        by_week.setdefault(week_of(d), []).append(g)

    weekly = [
        {
            "week": w.isoformat(),
            "phase": _phase(w),
            "left_sets": counts.get((w, "left"), 0),
            "right_sets": counts.get((w, "right"), 0),
            "sessions_with_both_arms": len(by_week.get(w, [])),
            "mean_gap_pct": _r(_mean(by_week.get(w, []))),
        }
        for w in _weeks()
    ]

    placebo = by_week.get(PLACEBO_WEEK, [])
    placebo_sd = statistics.stdev(placebo) if len(placebo) >= 2 else None
    final = [g for w in SCORED_WEEKS for g in by_week.get(w, [])]
    placebo_mean, final_mean = _mean(placebo), _mean(final)
    change = None if placebo_mean is None or final_mean is None else final_mean - placebo_mean

    dose = [w for w in _weeks() if _phase(w) == "dose"]
    avg = {
        arm: statistics.fmean(counts.get((w, arm), 0) for w in dose) for arm in ("left", "right")
    }
    low = "left" if HIGH_ARM == "right" else "right"
    delivered = avg[HIGH_ARM] >= HIGH_SETS_MIN and (
        LOW_SETS_RANGE[0] <= avg[low] <= LOW_SETS_RANGE[1]
    )
    delivery = {
        "delivered": delivered,
        "high_arm": HIGH_ARM,
        "avg_left_sets": _r(avg["left"]),
        "avg_right_sets": _r(avg["right"]),
        "dose_weeks": [w.isoformat() for w in dose],
        "weekly_left": [counts.get((w, "left"), 0) for w in dose],
        "weekly_right": [counts.get((w, "right"), 0) for w in dose],
    }

    end = LAST_WEEK + timedelta(days=7)
    if today < end:
        verdict, reason = (
            "pending",
            f"the single look is after the window closes ({end - timedelta(days=1)})",
        )
    elif not delivered:
        verdict, reason = "not_delivered", "dose delivery check failed"
    elif change is None:
        verdict, reason = (
            "inconclusive",
            "no paired sessions in the placebo week or the last two dose weeks",
        )
    elif (
        change >= SUPPORTED_MIN_CHANGE
        and placebo_sd is not None
        and change > SD_MULTIPLE * placebo_sd
    ):
        verdict, reason = "supported", "change clears +2.0 and twice the placebo SD"
    elif change < RULED_OUT_BELOW:
        verdict, reason = "ruled_out", "change is below +1.0"
    elif placebo_sd is None:
        verdict, reason = (
            "inconclusive",
            "placebo week had fewer than 2 paired sessions, so the noise bound is unknown",
        )
    else:
        verdict, reason = (
            "inconclusive",
            "change is between the bounds or does not exceed twice the placebo SD",
        )

    return {
        "slug": SLUG,
        "high_arm": HIGH_ARM,
        "weekly": weekly,
        "placebo_sd": _r(placebo_sd),
        "placebo_mean_gap_pct": _r(placebo_mean),
        "final_mean_gap_pct": _r(final_mean),
        "change": _r(change),
        "delivery": delivery,
        "verdict": verdict,
        "reason": reason,
    }
