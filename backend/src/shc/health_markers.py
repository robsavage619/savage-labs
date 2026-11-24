"""Long-horizon health markers: a registry of what to re-test, where the value lives and
what the published reference range is.

Not medical advice. Targets are published reference ranges copied from a cited vault note,
not clinical targets for the user; a marker whose note states no number carries no target
and reads ``no target set``. Definitions live here and in migration 0126 (a test keeps the
two identical); no personal value is stored anywhere in the registry. Latest values are
read at evaluation time from the table each marker names.
"""

from __future__ import annotations

from datetime import date
from typing import Any, NamedTuple

import duckdb

from shc.ai import vault

CLINICIAN = "set by clinician"
TREND_WINDOW_DAYS = 183
MIN_READINGS = 3
DIRECTIONS = ("higher_better", "lower_better", "in_range")


class Marker(NamedTuple):
    marker: str
    label: str
    domain: str
    source_table: str
    source_metric: str
    unit: str
    target_low: float | None
    target_high: float | None
    target_source: str | None
    retest_days: int
    direction: str


# source_metric: labs match on name (case-insensitive, `|` separates aliases); recovery and
# sleep name a column (duration_h is derived from the non-nap sleep window); measurements
# name a metric (step_count is summed per day, the rest averaged per day).
# Cadences are design choices. Only apoB and ALT cite a number: the other notes
# give percentiles, associations or no figure, so those markers carry no target.
MARKERS: tuple[Marker, ...] = (
    Marker("vo2max", "Aerobic fitness (VO2max)", "cardiorespiratory", "measurements",
           "vo2_max_whoop", "mL/kg/min", None, None, None, 90, "higher_better"),
    Marker("resting_hr", "Resting heart rate", "cardiovascular", "recovery",
           "rhr", "bpm", None, None, None, 14, "lower_better"),
    Marker("hrv", "Heart rate variability", "cardiovascular", "recovery",
           "hrv", "ms", None, None, None, 14, "higher_better"),
    Marker("bp_systolic", "Blood pressure (top number)", "cardiovascular", "measurements",
           "blood_pressure_systolic", "mmHg", None, None, None, 90, "lower_better"),
    Marker("bp_diastolic", "Blood pressure (bottom number)", "cardiovascular", "measurements",
           "blood_pressure_diastolic", "mmHg", None, None, None, 90, "lower_better"),
    Marker("apob", "ApoB (artery-clogging particle count)", "lipids", "labs",
           "ApoB|Apolipoprotein B", "mg/dL", None, 60.0, "apob.md", 180, "lower_better"),
    Marker("ldl_c", "LDL cholesterol", "lipids", "labs",
           "LDL Cholesterol (calc)", "mg/dL", None, None, None, 180, "lower_better"),
    Marker("hba1c", "HbA1c (3-month blood sugar)", "metabolic", "labs",
           "HbA1c", "%", None, None, None, 180, "lower_better"),
    Marker("alt", "ALT (liver enzyme)", "liver", "labs",
           "ALT", "U/L", None, 30.0, "attia-2023-ch6-crisis-of-abundance.md", 180, "lower_better"),
    Marker("waist", "Waist circumference", "body", "measurements",
           "waist_circumference_cm", "cm", None, None, None, 30, "lower_better"),
    Marker("grip", "Grip strength", "strength", "measurements",
           "grip_strength_kg", "kg", None, None, None, 90, "higher_better"),
    Marker("sleep_duration", "Sleep duration", "sleep", "sleep",
           "duration_h", "h", None, None, None, 14, "in_range"),
    Marker("sleep_consistency", "Sleep consistency", "sleep", "sleep",
           "sleep_consistency_pct", "%", None, None, None, 14, "higher_better"),
    Marker("steps", "Daily steps", "activity", "measurements",
           "step_count", "steps", None, None, None, 14, "higher_better"),
)  # fmt: skip

_RECOVERY_COLS = {"rhr", "hrv"}
_SLEEP_COLS = {"sleep_consistency_pct"}


def seed(conn: duckdb.DuckDBPyConnection) -> int:
    """Upsert every marker definition into ``health_markers``.

    Args:
        conn: Write connection.

    Returns:
        Number of markers written.

    Raises:
        RuntimeError: If a citation is set and the vault is unavailable.
        ValueError: If a citation is not a real vault note, or a direction/bound is invalid.
    """
    valid = vault.valid_citation_filenames()
    for m in MARKERS:
        if m.direction not in DIRECTIONS:
            raise ValueError(f"{m.marker}: unknown direction {m.direction!r}")
        if m.target_source is None:
            if m.target_low is not None or m.target_high is not None:
                raise ValueError(f"{m.marker}: a target needs a cited source")
            continue
        if m.target_source != CLINICIAN:
            if not valid:
                raise RuntimeError("vault unavailable: cannot validate target citations")
            if m.target_source not in valid:
                raise ValueError(f"{m.marker}: {m.target_source!r} is not a vault note")
        if _bounds(m.direction, m.target_low, m.target_high) == (None, None):
            raise ValueError(f"{m.marker}: direction {m.direction} has no usable bound")
    conn.executemany(
        """
        INSERT INTO health_markers (marker, label, domain, source_table, source_metric, unit,
            target_low, target_high, target_source, retest_days, direction)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (marker) DO UPDATE SET label = excluded.label, domain = excluded.domain,
            source_table = excluded.source_table, source_metric = excluded.source_metric,
            unit = excluded.unit, target_low = excluded.target_low,
            target_high = excluded.target_high, target_source = excluded.target_source,
            retest_days = excluded.retest_days, direction = excluded.direction
        """,
        [list(m) for m in MARKERS],
    )
    return len(MARKERS)


def _bounds(
    direction: str, low: float | None, high: float | None
) -> tuple[float | None, float | None]:
    if direction == "higher_better":
        return low, None
    if direction == "lower_better":
        return None, high
    return low, high


def _series(
    conn: duckdb.DuckDBPyConnection, table: str, metric: str, today: date
) -> list[tuple[date, float]]:
    """Dated readings, oldest first, one per day."""
    if table == "labs":
        names = [n.lower() for n in metric.split("|")]
        marks = ", ".join("?" * len(names))
        sql = (
            "SELECT collected_at::DATE d, avg(value) FROM labs "
            f"WHERE lower(name) IN ({marks}) AND value IS NOT NULL GROUP BY d ORDER BY d"
        )
        rows = conn.execute(sql, names).fetchall()
    elif table == "recovery" and metric in _RECOVERY_COLS:
        sql = (
            f"SELECT date d, avg({metric}) FROM recovery WHERE {metric} IS NOT NULL "
            "GROUP BY d ORDER BY d"
        )
        rows = conn.execute(sql).fetchall()
    elif table == "sleep" and metric == "duration_h":
        rows = conn.execute(
            "SELECT night_date d, sum(epoch(ts_out - ts_in)) / 3600.0 FROM sleep "
            "WHERE NOT COALESCE(is_nap, FALSE) AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
            "GROUP BY d ORDER BY d"
        ).fetchall()
    elif table == "sleep" and metric in _SLEEP_COLS:
        sql = (
            f"SELECT night_date d, avg({metric}) FROM sleep WHERE {metric} IS NOT NULL "
            "AND NOT COALESCE(is_nap, FALSE) GROUP BY d ORDER BY d"
        )
        rows = conn.execute(sql).fetchall()
    elif table == "measurements":
        agg = "sum" if metric == "step_count" else "avg"
        # Today's step total is a partial day; every other metric is a point reading.
        cutoff = " AND ts::DATE < ?" if metric == "step_count" else ""
        params: list[Any] = [metric] + ([today] if cutoff else [])
        rows = conn.execute(
            f"SELECT ts::DATE d, {agg}(value_num) FROM measurements "
            f"WHERE metric = ? AND value_num IS NOT NULL{cutoff} GROUP BY d ORDER BY d",
            params,
        ).fetchall()
    else:
        raise ValueError(f"no reader for {table}.{metric}")
    return [(d, float(v)) for d, v in rows]


def _trend(series: list[tuple[date, float]], today: date) -> dict[str, Any]:
    """Least-squares slope per 30 days over the last 6 months, or the last 3 readings."""
    recent = [p for p in series if (today - p[0]).days <= TREND_WINDOW_DAYS]
    pts = recent if len(recent) >= MIN_READINGS else series[-MIN_READINGS:]
    n = len(pts)
    base: dict[str, Any] = {"n": n, "slope_per_30d": None, "fitted_latest": None}
    xs = [(d - pts[0][0]).days for d, _ in pts]
    mx = sum(xs) / n if n else 0.0
    sxx = sum((x - mx) ** 2 for x in xs)
    if n < MIN_READINGS or sxx == 0:
        return base | {"note": "not enough readings"}
    my = sum(v for _, v in pts) / n
    slope = sum((x - mx) * (v - my) for x, (_, v) in zip(xs, pts, strict=True)) / sxx
    return base | {
        "slope_per_30d": round(slope * 30, 3),
        "fitted_latest": my + slope * (xs[-1] - mx),
        "slope_per_day": slope,
    }


def _status(value: float, age: int, m: dict[str, Any], trend: dict[str, Any]) -> str:
    if age > m["retest_days"]:
        return "stale"
    low, high = _bounds(m["direction"], m["target_low"], m["target_high"])
    if low is None and high is None:
        return "no target set"
    if (low is not None and value < low) or (high is not None and value > high):
        return "out of range"
    slope = trend.get("slope_per_day")
    if slope is not None:
        projected = trend["fitted_latest"] + slope * m["retest_days"]
        if (low is not None and projected < low) or (high is not None and projected > high):
            return "drifting"
    return "on target"


def evaluate(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> list[dict[str, Any]]:
    """Latest value, trend and status for every registered marker.

    Args:
        conn: Read connection with the ``health_markers`` table.
        today: Reference day; defaults to the current date.

    Returns:
        One dict per marker: label, unit, value, date, age_days, target, trend, status.
    """
    today = today or date.today()
    cur = conn.execute(
        "SELECT marker, label, domain, source_table, source_metric, unit, target_low, "
        "target_high, target_source, retest_days, direction FROM health_markers ORDER BY marker"
    )
    cols = [c[0] for c in cur.description]
    out = []
    for row in cur.fetchall():
        m = dict(zip(cols, row, strict=True))
        series = _series(conn, m["source_table"], m["source_metric"], today)
        item: dict[str, Any] = {
            "marker": m["marker"],
            "label": m["label"],
            "domain": m["domain"],
            "unit": m["unit"],
            "retest_days": m["retest_days"],
            "target": {
                "low": m["target_low"],
                "high": m["target_high"],
                "direction": m["direction"],
                "source": m["target_source"] if m["target_source"] else "no target set",
            },
        }
        if not series:
            out.append(item | {"value": None, "date": None, "age_days": None,
                               "trend": None, "status": "no data"})  # fmt: skip
            continue
        last_day, value = series[-1]
        age = (today - last_day).days
        trend = _trend(series, today)
        public_trend = {k: v for k, v in trend.items() if k in ("n", "slope_per_30d", "note")}
        public_trend["unit"] = f"{m['unit']} per 30 days"
        out.append(
            item
            | {
                "value": value,
                "date": last_day.isoformat(),
                "age_days": age,
                "trend": public_trend,
                "status": _status(value, age, m, trend),
            }
        )
    return out


def names_due(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> list[str]:
    """Labels of markers that are stale, drifting or out of range; names only, no values."""
    due = {"stale", "drifting", "out of range"}
    return [r["label"] for r in evaluate(conn, today) if r["status"] in due]
