from __future__ import annotations

"""Deterministic exercise-name → muscle classifier.

Canonical muscle vocabulary (matches muscle_volume_targets + BodyDiagram keys):
    chest, front_delts, side_delts, rear_delts, triceps, biceps, forearms,
    lats, mid_back, traps, lower_back, quads, hamstrings, glutes, adductors,
    calves, abs

Rules are ordered specific-before-generic.  Returns (primary, secondaries) or
None if the name cannot be classified confidently.
"""

import logging

import duckdb

log = logging.getLogger(__name__)

# Canonical muscle vocabulary — must match muscle_volume_targets keys exactly.
MUSCLES = frozenset(
    {
        "chest",
        "front_delts",
        "side_delts",
        "rear_delts",
        "triceps",
        "biceps",
        "forearms",
        "lats",
        "mid_back",
        "traps",
        "lower_back",
        "quads",
        "hamstrings",
        "glutes",
        "adductors",
        "calves",
        "abs",
    }
)


def classify_exercise(name: str) -> tuple[str, list[str]] | None:
    """Return (primary_muscle, [secondary_muscles]) or None if unclassifiable.

    Rules are specific-before-generic so longer/narrower keywords win.
    The caller is responsible for inserting into exercise_muscle_map.
    """
    n = name.lower()

    # ── Calves ───────────────────────────────────────────────────────────────
    if "calf" in n or "calve" in n:
        return "calves", []

    # ── Adductors ────────────────────────────────────────────────────────────
    if "adduction" in n or "adductor" in n:
        return "adductors", ["glutes"]

    # ── Glutes (abduction keywords → glutes, not adductors) ─────────────────
    if "abduction" in n or "abductor" in n:
        return "glutes", ["adductors"]
    if "hip thrust" in n or "glute bridge" in n or "glute" in n or "kickback" in n:
        return "glutes", ["hamstrings"]

    # ── Hamstrings ───────────────────────────────────────────────────────────
    if (
        "rdl" in n
        or "romanian" in n
        or "stiff" in n
        or "leg curl" in n
        or "hamstring" in n
        or ("lying" in n and "curl" in n)
    ):
        return "hamstrings", ["glutes"]

    # ── Deadlift (non-romanian/stiff → posterior chain / glute primary) ──────
    if "deadlift" in n:
        return "glutes", ["hamstrings", "lower_back", "traps"]

    # ── Squat / quad compounds ───────────────────────────────────────────────
    if "leg extension" in n or "quad" in n:
        return "quads", []
    if (
        "squat" in n
        or "lunge" in n
        or "leg press" in n
        or "goblet" in n
        or "split squat" in n
        or "bulgarian" in n
        or "step-up" in n
        or "step up" in n
    ):
        return "quads", ["glutes", "hamstrings"]

    # ── Lower back / back extension ──────────────────────────────────────────
    if "back extension" in n or "hyperextension" in n or "bird dog" in n:
        return "lower_back", []

    # ── Pullover (lats primary, chest secondary) ──────────────────────────────
    if "pullover" in n:
        return "lats", ["chest"]

    # ── Glute / posterior-chain hybrids ──────────────────────────────────────
    if "kettlebell swing" in n or "kb swing" in n:
        return "glutes", ["hamstrings", "lower_back"]

    # ── Arms ─────────────────────────────────────────────────────────────────
    if "reverse curl" in n:
        return "forearms", ["biceps"]
    if (
        "curl" in n
        or "hammer" in n
        or "concentration" in n
        or "preacher" in n
        or "drag curl" in n
        or "bicep" in n
    ):
        return "biceps", []
    if (
        "tricep" in n
        or "pushdown" in n
        or "dip" in n  # bench dip, machine dip, ring dip, etc.
        or ("overhead" in n and "extension" in n)
        or "skull" in n
    ):
        return "triceps", []

    # ── Chest ────────────────────────────────────────────────────────────────
    if (
        "fly" in n
        or "crossover" in n
        or "pec" in n
        or "chest" in n
        or "bench press" in n
        or "decline" in n
        or "incline" in n
    ):
        return "chest", ["front_delts", "triceps"]

    # ── Shoulders ────────────────────────────────────────────────────────────
    if "lateral raise" in n or "side raise" in n or "shoulder raise" in n:
        return "side_delts", []
    if "front raise" in n:
        return "front_delts", []
    if (
        "rear delt" in n
        or "reverse fly" in n
        or "face pull" in n
        or "internal rotation" in n
        or "external rotation" in n
        or "iron cross" in n
        or "band pullapart" in n
        or "clamshell" in n
        or "scapular" in n  # scapular retraction, scapular squeeze
        or "shoulder squeeze" in n
    ):
        return "rear_delts", ["traps"]
    if "shrug" in n:
        return "traps", []
    if "upright row" in n:
        return "traps", ["side_delts"]

    # ── Back ─────────────────────────────────────────────────────────────────
    if (
        "row" in n
        or "pulldown" in n
        or "pull-up" in n
        or "pullup" in n
        or "pull down" in n
        or "chin" in n
        or "high row" in n
        or "iso row" in n
        or "iso-lateral row" in n
    ):
        return "lats", ["mid_back", "biceps"]

    # ── Press / overhead ─────────────────────────────────────────────────────
    if "press" in n or "overhead" in n or "military" in n or "shoulder press" in n:
        return "front_delts", ["side_delts", "triceps"]

    # ── Core ─────────────────────────────────────────────────────────────────
    if (
        "crunch" in n
        or "ab " in n
        or "oblique" in n
        or "plank" in n
        or "sit-up" in n
        or "twist" in n
        or "leg raise" in n
        or "knee raise" in n
        or "leg pull-in" in n
        or "leg pull in" in n
        or "wood chop" in n
        or "side bend" in n
        or "scissor" in n
        or "flutter kick" in n
        or "mountain climber" in n
        or "medicine ball slam" in n
        or "med ball slam" in n
        or "landmine rotation" in n
        or "core rotation" in n
        or "cable rotation" in n
    ):
        return "abs", []

    # ── Hip flexor / glute band work ──────────────────────────────────────────
    if "hip flexor" in n:
        return "quads", []  # hip flexors assist quads; no dedicated canonical key
    if "fire hydrant" in n:
        return "glutes", ["adductors"]

    # ── High pull (band/cable) → traps + upper back ───────────────────────────
    if "high pull" in n:
        return "traps", ["rear_delts"]

    return None


def backfill_exercise_map(conn: duckdb.DuckDBPyConnection) -> None:
    """Insert classify_exercise() results for every unmapped exercise in the DB.

    Skips exercises already in exercise_muscle_map (uses INSERT OR IGNORE /
    ON CONFLICT DO NOTHING).  Remaps any lingering 'core' primary → 'abs'.
    Logs a warning if >20% of trailing-90d sets are still unmapped after the run.
    """
    # Fix any lingering core→abs taxonomy drift first.
    conn.execute(
        "UPDATE exercise_muscle_map SET primary_muscle = 'abs' WHERE primary_muscle = 'core'"
    )

    # Fetch every exercise name not yet in the map.
    unmapped: list[str] = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT ws.exercise
            FROM workout_sets_dedup ws
            LEFT JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
            WHERE m.exercise_name IS NULL
            ORDER BY ws.exercise
            """
        ).fetchall()
    ]

    inserted = 0
    skipped: list[str] = []
    for ex in unmapped:
        result = classify_exercise(ex)
        if result is None:
            skipped.append(ex)
            continue
        primary, secondaries = result
        conn.execute(
            """
            INSERT INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles)
            VALUES (?, ?, ?)
            ON CONFLICT (exercise_name) DO NOTHING
            """,
            [ex, primary, secondaries],
        )
        inserted += 1

    if skipped:
        # Name every unclassifiable exercise (#25): a truncated list hides the
        # exact lifts that will silently contribute zero volume, so the full set
        # is logged rather than skipped[:20].
        log.warning(
            "backfill_exercise_map: %d exercises could not be classified and will"
            " contribute ZERO volume until mapped: %s",
            len(skipped),
            ", ".join(skipped),
        )
    log.info(
        "backfill_exercise_map: inserted %d, skipped %d (total unmapped input: %d)",
        inserted,
        len(skipped),
        len(unmapped),
    )

    _warn_if_high_unmapped(conn)


def _warn_if_high_unmapped(conn: duckdb.DuckDBPyConnection) -> None:
    """Log a loud warning if >20% of trailing-90d working sets are unmapped."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE m.exercise_name IS NULL) AS unmapped,
            COUNT(*)                                         AS total
        FROM workout_sets_dedup ws
        LEFT JOIN exercise_muscle_map m ON ws.exercise = m.exercise_name
        WHERE ws.started_at::DATE >= (CURRENT_DATE - INTERVAL '90 days')
          AND NOT ws.is_warmup AND ws.weight_kg > 0 AND ws.reps > 0
        """
    ).fetchone()
    if not row or not row[1]:
        return
    unmapped, total = row
    pct = unmapped / total
    if pct > 0.20:
        log.warning(
            "UNMAPPED SETS ALERT: %.0f%% of trailing-90d working sets (%d/%d) have"
            " no muscle map entry — volume reporting is degraded",
            pct * 100,
            unmapped,
            total,
        )
