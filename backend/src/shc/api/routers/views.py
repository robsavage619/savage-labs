from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, write_ctx

router = APIRouter(tags=["views"])


class ViewIn(BaseModel):
    path: str = Field(min_length=1, max_length=80)


def surface_of(path: str) -> str:
    """Collapse a route to its surface: '/lab/x?y' -> '/lab'."""
    head = path.split("?", 1)[0].strip("/").split("/", 1)[0]
    return f"/{head}" if head else "/"


@router.post("/views", dependencies=[Depends(require_admin_key)])
async def record_view(body: ViewIn) -> dict[str, str]:
    path = surface_of(body.path)
    async with write_ctx() as conn:
        conn.execute(
            "INSERT INTO page_views (day, path, n) VALUES (current_date, ?, 1) "
            "ON CONFLICT (day, path) DO UPDATE SET n = page_views.n + 1",
            [path],
        )
    return {"path": path}


@router.get("/views")
def view_counts(days: int = 30) -> dict[str, Any]:
    """Opens per surface over the last `days`, most opened first."""
    since = date.today() - timedelta(days=days - 1)
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT path, sum(n), count(*), max(day) FROM page_views WHERE day >= ? "
            "GROUP BY 1 ORDER BY 2 DESC",
            [since],
        ).fetchall()
        first = conn.execute("SELECT min(day) FROM page_views").fetchone()
    finally:
        conn.close()
    return {
        "days": days,
        "counting_since": first[0].isoformat() if first and first[0] else None,
        "surfaces": [
            {"path": p, "opens": int(n), "days_opened": int(d), "last": last.isoformat()}
            for p, n, d, last in rows
        ],
    }
