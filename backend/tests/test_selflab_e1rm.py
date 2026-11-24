"""The n-of-1 engine's e1RM extractor must agree with the engine's (invariants 13 and 19)."""

from __future__ import annotations

from datetime import date

import pytest

from shc import selflab


def _set(conn, exercise: str, day: date, weight: float, reps: int, rpe: float | None) -> None:
    wid = f"w-{exercise}-{day}"
    conn.execute(
        "INSERT OR IGNORE INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES (?, 'hevy', ?, 'strength', ?)",
        [wid, f"{day} 08:00:00", f"h{wid}"],
    )
    conn.execute(
        "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, rpe, "
        "is_warmup, content_hash) VALUES (?, ?, 0, ?, ?, ?, ?, FALSE, ?)",
        [f"{wid}s", wid, exercise, weight, reps, rpe, f"c{wid}"],
    )


def test_a_combined_total_logged_before_the_switch_reads_per_hand(conn) -> None:
    # Seated Dumbbell Curl was logged as a two-dumbbell total until 2026-09-24:
    # 40 kg total is 20 kg per hand; RPE 8 credits 2 reps, so 12 effective reps.
    _set(conn, "Seated Dumbbell Curl", date(2026, 9, 1), 40.0, 10, 8.0)
    assert selflab._top_set_e1rm(conn, "Seated Dumbbell Curl", date(2026, 9, 1)) == pytest.approx(
        20.0 * (1 + 12 / 30)
    )


def test_a_per_hand_set_after_the_switch_is_unchanged(conn) -> None:
    _set(conn, "Seated Dumbbell Curl", date(2026, 10, 1), 20.0, 10, 8.0)
    assert selflab._top_set_e1rm(conn, "Seated Dumbbell Curl", date(2026, 10, 1)) == pytest.approx(
        20.0 * (1 + 12 / 30)
    )


def test_a_set_with_no_rpe_adds_no_effort_credit(conn) -> None:
    _set(conn, "Bench Press (Barbell)", date(2026, 10, 1), 80.0, 8, None)
    assert selflab._top_set_e1rm(conn, "Bench Press (Barbell)", date(2026, 10, 1)) == pytest.approx(
        80.0 * (1 + 8 / 30)
    )
