from __future__ import annotations

import difflib
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from shc.auth.keychain import load_token
from shc.config import settings
from shc.db.schema import get_read_conn, write_ctx

log = logging.getLogger(__name__)

HEVY_BASE = "https://api.hevyapp.com"
_PAGE_SIZE = 10  # Hevy default page size


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _api_key() -> str:
    # Keychain takes priority; env var (HEVY_API_KEY) is the fallback
    key = load_token("hevy", "api_key") or settings.hevy_api_key
    if not key:
        raise RuntimeError("Hevy API key not found — run: shc auth hevy <key>")
    return key


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{HEVY_BASE}{path}",
            params=params,
            headers={"api-key": _api_key()},
            timeout=30.0,
        )
        resp.raise_for_status()
    return resp.json()


async def _post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{HEVY_BASE}{path}",
            json=body,
            headers={"api-key": _api_key(), "Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
    return resp.json()


async def _put(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{HEVY_BASE}{path}",
            json=body,
            headers={"api-key": _api_key(), "Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
    return resp.json()


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


# ── Exercise templates ────────────────────────────────────────────────────────


async def sync_exercise_templates() -> int:
    """Fetch all Hevy exercise templates and cache in hevy_exercise_templates."""
    page = 1
    total = 0
    while True:
        data = await _get("/v1/exercise_templates", {"page": page, "pageSize": _PAGE_SIZE})
        templates = data.get("exercise_templates", [])
        if not templates:
            break
        async with write_ctx() as conn:
            for t in templates:
                secondary = json.dumps(t.get("muscle_groups", []))
                conn.execute(
                    """
                    INSERT INTO hevy_exercise_templates
                        (id, title, primary_muscle_group, secondary_muscle_groups, category, synced_at)
                    VALUES ($id, $title, $pmg, $smg, $cat, now())
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        primary_muscle_group = EXCLUDED.primary_muscle_group,
                        secondary_muscle_groups = EXCLUDED.secondary_muscle_groups,
                        category = EXCLUDED.category,
                        synced_at = EXCLUDED.synced_at
                    """,
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "pmg": t.get("primary_muscle_group"),
                        "smg": secondary,
                        "cat": t.get("category"),
                    },
                )
        total += len(templates)
        page_count = data.get("page_count", 1)
        if page >= page_count:
            break
        page += 1
    log.info("synced %d Hevy exercise templates", total)
    return total


def _find_template_id(name: str, templates: list[tuple[str, str]]) -> str | None:
    """Fuzzy-match exercise name to a Hevy template_id.

    templates: list of (id, title) tuples from hevy_exercise_templates.
    Returns best match id if similarity ≥ 0.6, else None.
    """
    titles = [t[1] for t in templates]
    matches = difflib.get_close_matches(name, titles, n=1, cutoff=0.6)
    if matches:
        matched_title = matches[0]
        for tid, ttitle in templates:
            if ttitle == matched_title:
                return tid
    return None


# ── Workout sync (Hevy → SHC) ─────────────────────────────────────────────────


def _map_workout_to_db(w: dict) -> tuple[dict, list[dict]]:
    """Convert a Hevy workout JSON into (workout_row, set_rows)."""
    hevy_id = w["id"]
    workout_id = f"hevy_{hevy_id}"
    started_at = w.get("start_time")
    ended_at = w.get("end_time")
    notes = w.get("description") or w.get("title")
    chash = _content_hash("hevy", hevy_id, str(w.get("updated_at", "")))

    workout_row = {
        "id": workout_id,
        "source": "hevy",
        "started_at": started_at,
        "ended_at": ended_at,
        "kind": "strength",
        "notes": notes,
        "content_hash": chash,
    }

    set_rows = []
    for ex in w.get("exercises", []):
        exercise_name = ex.get("title", "Unknown")
        for idx, s in enumerate(ex.get("sets", [])):
            set_hash = _content_hash("hevy", hevy_id, exercise_name, str(idx))
            set_id = f"hevy_set_{set_hash}"
            set_rows.append({
                "id": set_id,
                "workout_id": workout_id,
                "exercise": exercise_name,
                "set_idx": idx,
                "reps": s.get("reps"),
                "weight_kg": s.get("weight_kg"),
                "rpe": s.get("rpe"),
                "is_warmup": s.get("type") == "warmup",
                "content_hash": set_hash,
            })
    return workout_row, set_rows


async def _upsert_workout(conn: Any, workout_row: dict, set_rows: list[dict]) -> bool:
    """Upsert one workout and its sets. Returns True if workout was new/changed."""
    existing = conn.execute(
        "SELECT content_hash FROM workouts WHERE id = $id",
        {"id": workout_row["id"]},
    ).fetchone()

    if existing and existing[0] == workout_row["content_hash"]:
        return False

    conn.execute(
        """
        INSERT INTO workouts (id, source, started_at, ended_at, kind, notes, content_hash)
        VALUES ($id, $source, $started_at, $ended_at, $kind, $notes, $content_hash)
        ON CONFLICT (id) DO UPDATE SET
            ended_at = EXCLUDED.ended_at,
            notes = EXCLUDED.notes,
            content_hash = EXCLUDED.content_hash
        WHERE EXCLUDED.content_hash != workouts.content_hash
        """,
        workout_row,
    )
    for s in set_rows:
        conn.execute(
            """
            INSERT INTO workout_sets
                (id, workout_id, exercise, set_idx, reps, weight_kg, rpe, is_warmup, content_hash)
            VALUES ($id, $workout_id, $exercise, $set_idx, $reps, $weight_kg, $rpe, $is_warmup, $content_hash)
            ON CONFLICT (id) DO NOTHING
            """,
            s,
        )
    return True


async def _update_working_weights_from_hevy(conn: Any) -> None:
    conn.execute("""
        INSERT INTO working_weights (exercise, weight_kg, updated_at, source)
        SELECT
            ws.exercise,
            MAX(ws.weight_kg) AS weight_kg,
            MAX(w.started_at) AS updated_at,
            'hevy'
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE
          AND ws.weight_kg IS NOT NULL
          AND ws.weight_kg > 0
          AND w.source = 'hevy'
        GROUP BY ws.exercise
        ON CONFLICT (exercise) DO UPDATE SET
            weight_kg = EXCLUDED.weight_kg,
            updated_at = EXCLUDED.updated_at,
            source = EXCLUDED.source
        WHERE EXCLUDED.weight_kg > working_weights.weight_kg
    """)


async def sync_workouts() -> dict[str, int]:
    """Pull workouts from Hevy and upsert into the local DB.

    Uses GET /v1/workouts/events for incremental sync after initial load.
    Cursor stored in oauth_state(source='hevy').
    """
    # Load cursor
    read_conn = get_read_conn()
    try:
        row = read_conn.execute(
            "SELECT cursor FROM oauth_state WHERE source = 'hevy'"
        ).fetchone()
    finally:
        read_conn.close()

    cursor = row[0] if row and row[0] else None
    synced = 0
    deleted = 0

    if cursor:
        # Incremental sync via events
        page = 1
        while True:
            data = await _get(
                "/v1/workouts/events",
                {"since": cursor, "page": page, "pageSize": _PAGE_SIZE},
            )
            events = data.get("events", [])
            if not events:
                break

            async with write_ctx() as conn:
                for ev in events:
                    ev_type = ev.get("type")
                    if ev_type == "deleted":
                        wid = f"hevy_{ev.get('workout_id', '')}"
                        conn.execute("DELETE FROM workout_sets WHERE workout_id = $id", {"id": wid})
                        conn.execute("DELETE FROM workouts WHERE id = $id", {"id": wid})
                        deleted += 1
                    elif ev_type == "updated":
                        workout_row, set_rows = _map_workout_to_db(ev["workout"])
                        if await _upsert_workout(conn, workout_row, set_rows):
                            synced += 1

            page_count = data.get("page_count", 1)
            if page >= page_count:
                break
            page += 1
    else:
        # Full initial sync
        page = 1
        while True:
            data = await _get("/v1/workouts", {"page": page, "pageSize": _PAGE_SIZE})
            workouts = data.get("workouts", [])
            if not workouts:
                break
            async with write_ctx() as conn:
                for w in workouts:
                    workout_row, set_rows = _map_workout_to_db(w)
                    if await _upsert_workout(conn, workout_row, set_rows):
                        synced += 1
            page_count = data.get("page_count", 1)
            if page >= page_count:
                break
            page += 1

    # Update working weights and cursor
    async with write_ctx() as conn:
        await _update_working_weights_from_hevy(conn)
        conn.execute(
            """
            INSERT INTO oauth_state (source, last_sync_at, cursor, needs_reauth)
            VALUES ('hevy', $ts, $cursor, FALSE)
            ON CONFLICT (source) DO UPDATE SET
                last_sync_at = EXCLUDED.last_sync_at,
                cursor = EXCLUDED.cursor,
                needs_reauth = FALSE
            """,
            {"ts": datetime.now(UTC).isoformat(), "cursor": datetime.now(UTC).isoformat()},
        )

    log.info("Hevy sync complete: %d synced, %d deleted", synced, deleted)
    return {"synced": synced, "deleted": deleted}


# ── Push routine (SHC plan → Hevy) ───────────────────────────────────────────


def _parse_reps(reps_str: str | int | None) -> int | None:
    """Parse reps field which may be '5', '5-8', '8-12', or an int."""
    if reps_str is None:
        return None
    s = str(reps_str).strip()
    # Take first number in range like "8-12"
    part = s.split("-")[0].split("–")[0].strip()
    try:
        return int(part)
    except ValueError:
        return None


async def push_routine(plan: dict) -> dict:
    """Push an AI workout plan as a Hevy routine.

    If a routine for today already exists in hevy_routines, updates it.
    Returns the Hevy API response.
    """
    today = datetime.now(UTC).date().isoformat()
    title = f"SHC Plan — {today}"

    # Check template cache
    read_conn = get_read_conn()
    try:
        count = read_conn.execute(
            "SELECT COUNT(*) FROM hevy_exercise_templates"
        ).fetchone()[0]
        existing_routine = read_conn.execute(
            "SELECT routine_id FROM hevy_routines WHERE date = $d", {"d": today}
        ).fetchone()
    finally:
        read_conn.close()

    if count == 0:
        log.info("No exercise templates cached — syncing now")
        await sync_exercise_templates()

    # Load templates (may have just been populated)
    read_conn = get_read_conn()
    try:
        templates: list[tuple[str, str]] = read_conn.execute(
            "SELECT id, title FROM hevy_exercise_templates"
        ).fetchall()
    finally:
        read_conn.close()

    exercises = _plan_to_hevy_exercises(plan, templates)

    body = {
        "routine": {
            "title": title,
            "notes": _routine_notes(plan),
            "exercises": exercises,
        }
    }

    if existing_routine:
        routine_id = existing_routine[0]
        log.info("Updating existing Hevy routine %s for %s", routine_id, today)
        result = await _put(f"/v1/routines/{routine_id}", body)
    else:
        log.info("Creating new Hevy routine for %s", today)
        result = await _post("/v1/routines", body)
        routine_id = result.get("routine", {}).get("id") or result.get("id", "unknown")

    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO hevy_routines (date, routine_id, title, pushed_at)
            VALUES ($d, $rid, $title, now())
            ON CONFLICT (date) DO UPDATE SET
                routine_id = EXCLUDED.routine_id,
                title = EXCLUDED.title,
                pushed_at = EXCLUDED.pushed_at
            """,
            {"d": today, "rid": routine_id, "title": title},
        )

    log.info("Pushed routine '%s' (id=%s) to Hevy", title, routine_id)
    return result


def _plan_to_hevy_exercises(
    plan: dict, templates: list[tuple[str, str]]
) -> list[dict]:
    """Convert SHC workout plan blocks → Hevy routine exercises list."""
    exercises = []

    # Warmup exercises
    for wu in plan.get("warmup", []):
        name = wu.get("name", "Warmup")
        template_id = _find_template_id(name, templates)
        if template_id is None:
            log.debug("No template match for warmup '%s' — skipping", name)
            continue
        n_sets = wu.get("sets", 1)
        reps = _parse_reps(wu.get("reps"))
        duration = wu.get("duration_sec")
        exercises.append({
            "exercise_template_id": template_id,
            "superset_id": None,
            "notes": wu.get("notes") or "",
            "sets": [
                {
                    "type": "warmup",
                    "weight_kg": None,
                    "reps": reps,
                    "duration_seconds": duration,
                    "distance_meters": None,
                    "rpe": None,
                }
                for _ in range(n_sets)
            ],
        })

    # Main blocks
    for block in plan.get("blocks", []):
        for ex in block.get("exercises", []):
            name = ex.get("name", "")
            if not name:
                continue
            template_id = _find_template_id(name, templates)
            if template_id is None:
                log.warning("No template match for exercise '%s' — skipping", name)
                continue

            n_sets = ex.get("sets", 3)
            reps = _parse_reps(ex.get("reps"))
            weight_kg = ex.get("weight_kg")
            if weight_kg is None and ex.get("weight_lbs"):
                weight_kg = round(ex["weight_lbs"] / 2.20462, 2)
            rpe = ex.get("rpe_target")

            exercises.append({
                "exercise_template_id": template_id,
                "superset_id": None,
                "notes": ex.get("notes") or "",
                "sets": [
                    {
                        "type": "normal",
                        "weight_kg": weight_kg,
                        "reps": reps,
                        "duration_seconds": None,
                        "distance_meters": None,
                        "rpe": rpe,
                    }
                    for _ in range(n_sets)
                ],
            })

    return exercises


def _routine_notes(plan: dict) -> str:
    parts = []
    summary = plan.get("readiness_summary", "")
    if summary:
        parts.append(summary)
    rec = plan.get("recommendation", {})
    rationale = rec.get("rationale", "")
    if rationale:
        parts.append(rationale)
    clinical = plan.get("clinical_notes", [])
    if clinical:
        parts.append("Clinical: " + " | ".join(clinical[:2]))
    return "\n".join(parts)
