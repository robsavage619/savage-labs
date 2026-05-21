from __future__ import annotations

import uuid
from datetime import date, datetime

import duckdb
import pytest

from shc.db.schema import _apply_migrations


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    """Fresh in-memory DuckDB with all migrations applied."""
    c = duckdb.connect(":memory:")
    _apply_migrations(c)
    yield c
    c.close()


@pytest.fixture
def seed(conn: duckdb.DuckDBPyConnection):
    """Helper to insert a workout + sets and (optionally) a plan for a date.

    Returns a callable so tests can build up history declaratively.
    """

    def _add_workout(
        day: date,
        exercise: str,
        sets: list[tuple[float, int]],  # (weight_kg, reps)
        *,
        rpe: float | None = 8.0,
        source: str = "hevy",
        is_warmup: bool = False,
    ) -> None:
        wid = str(uuid.uuid4())
        started = datetime.combine(day, datetime.min.time())
        conn.execute(
            "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            [wid, source, started, "strength", wid],
        )
        for idx, (wkg, reps) in enumerate(sets):
            sid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO workout_sets
                    (id, workout_id, exercise, set_idx, reps, weight_kg, rpe,
                     is_warmup, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [sid, wid, exercise, idx, reps, wkg, rpe, is_warmup, sid],
            )

    def _add_plan(day: date, *, deload_prescribed: bool) -> None:
        import json

        conn.execute(
            "INSERT INTO workout_plans (date, plan_json, source) VALUES (?, ?, ?)",
            [day, json.dumps({"deload_prescribed": deload_prescribed}), "test"],
        )

    def _add_med(name: str, *, active: bool = True) -> None:
        conn.execute(
            "INSERT INTO medications (id, name, valid_from, valid_to) "
            "VALUES (?, ?, now(), ?)",
            [str(uuid.uuid4()), name, None if active else datetime.now()],
        )

    def _add_cardio(day: date, modality: str, duration_min: float, *,
                    avg_hr: int | None = None) -> None:
        cid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO cardio_sessions "
            "(id, date, modality, duration_min, avg_hr, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [cid, day, modality, duration_min, avg_hr, cid],
        )

    def _add_checkin(day: date, **fields) -> None:
        cols = ["date", "created_at"]
        vals: list = [day, datetime.now()]
        for k, v in fields.items():
            cols.append(k)
            vals.append(v)
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO daily_checkin ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )

    return type(
        "Seed",
        (),
        {
            "workout": staticmethod(_add_workout),
            "plan": staticmethod(_add_plan),
            "med": staticmethod(_add_med),
            "cardio": staticmethod(_add_cardio),
            "checkin": staticmethod(_add_checkin),
        },
    )


@pytest.fixture
def today() -> date:
    return date(2026, 5, 20)
