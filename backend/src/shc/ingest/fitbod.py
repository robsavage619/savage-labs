from __future__ import annotations

import csv
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def ingest_fitbod(csv_path: Path | None = None, rebuild: bool = False) -> dict[str, int]:
    """Parse WorkoutExport.csv and upsert into workouts + workout_sets + working_weights.

    When ``rebuild=True``, all existing Fitbod workouts and sets are deleted first.
    Use this when ingest logic changes (e.g. multiplier correction) and historical
    rows must be reprocessed from scratch.
    """
    from shc.config import settings
    from shc.db.schema import get_read_conn

    if csv_path is None:
        csv_path = settings.fitbod_csv_path

    if not csv_path.exists():
        raise FileNotFoundError(f"Fitbod CSV not found at {csv_path}")

    log.info("Parsing Fitbod CSV: %s", csv_path)

    if rebuild:
        conn = get_read_conn()
        before = conn.execute(
            "SELECT COUNT(*) FROM workout_sets ws JOIN workouts w ON w.id = ws.workout_id WHERE w.source = 'fitbod'"
        ).fetchone()[0]
        conn.execute("DELETE FROM workout_sets WHERE workout_id IN (SELECT id FROM workouts WHERE source = 'fitbod')")
        conn.execute("DELETE FROM workouts WHERE source = 'fitbod'")
        log.info("Rebuild: deleted %d existing Fitbod sets", before)

    # Group rows by session (same Date = same workout)
    sessions: dict[str, list[dict]] = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row["Date"].strip()
            sessions.setdefault(key, []).append(row)

    log.info("Found %d sessions, %d total sets", len(sessions), sum(len(v) for v in sessions.values()))

    conn = get_read_conn()
    workouts_inserted = 0
    sets_inserted = 0
    skipped = 0

    for date_str, rows in sessions.items():
        try:
            started_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            try:
                started_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                started_at = started_at.replace(tzinfo=timezone.utc)
            except ValueError:
                log.warning("Unparseable date: %s — skipping session", date_str)
                skipped += 1
                continue

        workout_hash = _content_hash("fitbod", date_str)
        workout_id = f"fitbod_{workout_hash}"

        existing = conn.execute(
            "SELECT id FROM workouts WHERE id = ?", [workout_id]
        ).fetchone()

        if not existing:
            conn.execute(
                """
                INSERT INTO workouts (id, source, started_at, kind, content_hash)
                VALUES (?, 'fitbod', ?, 'strength', ?)
                """,
                [workout_id, started_at, workout_hash],
            )
            workouts_inserted += 1

        for idx, row in enumerate(rows):
            try:
                # Fitbod's Weight(kg) is per-implement (e.g. one dumbbell).
                # The `multiplier` column is 2.0 for paired dumbbells, 1.0 for
                # barbells/machines/cables. Multiply to get total weight lifted,
                # which is the convention used elsewhere in SHC (and what Hevy
                # reports).
                raw_weight = float(row.get("Weight(kg)", 0) or 0)
                multiplier = float(row.get("multiplier", 1) or 1)
                weight_kg = raw_weight * multiplier
                reps = int(float(row.get("Reps", 0) or 0))
                is_warmup = row.get("isWarmup", "false").strip().lower() == "true"
                exercise = row.get("Exercise", "").strip()
                if not exercise:
                    continue

                set_hash = _content_hash("fitbod", date_str, exercise, str(idx))
                set_id = f"fitbod_set_{set_hash}"

                set_exists = conn.execute(
                    "SELECT id FROM workout_sets WHERE id = ?", [set_id]
                ).fetchone()
                if not set_exists:
                    conn.execute(
                        """
                        INSERT INTO workout_sets
                            (id, workout_id, exercise, set_idx, reps, weight_kg, is_warmup, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [set_id, workout_id, exercise, idx, reps,
                         weight_kg if weight_kg > 0 else None,
                         is_warmup, set_hash],
                    )
                    sets_inserted += 1
            except Exception as e:
                log.debug("Skipping row in %s: %s", date_str, e)

    # Update working_weights from most recent non-warmup max per exercise
    log.info("Rebuilding working_weights...")
    conn.execute("""
        INSERT INTO working_weights (exercise, weight_kg, updated_at, source)
        SELECT
            ws.exercise,
            MAX(ws.weight_kg) AS weight_kg,
            MAX(w.started_at) AS updated_at,
            'fitbod'
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE
          AND ws.weight_kg IS NOT NULL
          AND ws.weight_kg > 0
          AND w.source = 'fitbod'
        GROUP BY ws.exercise
        ON CONFLICT (exercise) DO UPDATE SET
            weight_kg = EXCLUDED.weight_kg,
            updated_at = EXCLUDED.updated_at,
            source = EXCLUDED.source
    """)

    conn.close()

    result = {
        "sessions": len(sessions),
        "workouts_inserted": workouts_inserted,
        "sets_inserted": sets_inserted,
        "skipped": skipped,
    }
    log.info("Fitbod ingest complete: %s", result)
    return result
