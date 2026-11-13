"""What a pickleball session costs the heart, quarter by quarter.

Read-only and gate-free. A falling session HR can be fitness, a beta-blocker,
easier games or strap fit; propranolol days are only known when the check-in
marks them, so the caller must not read this as fitness alone.
"""

from __future__ import annotations

from typing import Any

import duckdb

_MIN_SESSIONS = 8


def hr_cost(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Median session HR, peak HR, minutes and kcal/min per quarter with enough sessions."""
    rows = conn.execute(
        """
        WITH s AS (
            SELECT started_at, avg_hr, max_hr, kcal,
                   date_diff('minute', started_at, ended_at) AS mins
            FROM workouts
            WHERE source = 'whoop' AND sport_name = 'pickleball' AND avg_hr IS NOT NULL
        )
        SELECT year(started_at) AS y, quarter(started_at) AS q, count(*),
               median(avg_hr), median(max_hr), median(mins),
               median(kcal / nullif(mins, 0))
        FROM s GROUP BY 1, 2 HAVING count(*) >= ? ORDER BY 1, 2
        """,
        [_MIN_SESSIONS],
    ).fetchall()
    return [
        {
            "quarter": f"{y} Q{q}",
            "sessions": int(n),
            "avg_hr": round(float(a)),
            "peak_hr": round(float(p)) if p is not None else None,
            "minutes": round(float(m)) if m is not None else None,
            "kcal_per_min": round(float(k), 1) if k is not None else None,
        }
        for y, q, n, a, p, m, k in rows
    ]
