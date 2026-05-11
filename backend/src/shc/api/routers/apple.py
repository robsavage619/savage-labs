from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from shc.config import settings
from shc.db.schema import write_ctx
from shc.ingest.apple import _store_hae

log = logging.getLogger(__name__)

router = APIRouter(tags=["apple"])

_key_header = APIKeyHeader(name="X-SHC-Key", auto_error=False)


def _require_key(key: Annotated[str | None, Depends(_key_header)]) -> None:
    """Reject requests that don't carry the configured webhook key."""
    if not settings.apple_webhook_key:
        raise HTTPException(status_code=503, detail="apple_webhook_key not configured")
    if key != settings.apple_webhook_key:
        raise HTTPException(status_code=401, detail="invalid key")


@router.post("/apple/hae", dependencies=[Depends(_require_key)])
async def apple_hae_webhook(request: Request) -> dict[str, Any]:
    """Receive a Health Auto Export JSON payload and upsert into measurements.

    Health Auto Export → Settings → Automations → add REST API export →
    set URL to http://<tailscale-host>:8000/api/apple/hae, add header
    X-SHC-Key: <apple_webhook_key>.

    Payload shape (HAE default):
        {"data": {"Heart Rate Variability": [{"date": "...", "qty": 45.2, "units": "ms"}]}}
    """
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    content_hash = hashlib.sha256(await request.body()).hexdigest()[:16]

    try:
        await _store_hae(data, content_hash)
    except Exception as exc:
        log.exception("HAE webhook ingest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    metrics = data.get("data", {})
    metric_count = len(metrics) if isinstance(metrics, dict) else 0
    sample_count = (
        sum(len(v) for v in metrics.values() if isinstance(v, list))
        if isinstance(metrics, dict)
        else 0
    )
    log.info("HAE webhook: %d metrics, %d samples", metric_count, sample_count)
    return {"ok": True, "metrics": metric_count, "samples": sample_count}


# Shortcut key → db metric name + SI unit
# Unit-neutral metrics (bpm, %, kcal, count, min) are the same regardless of locale.
_SHORTCUT_UNITS: dict[str, tuple[str, str]] = {
    # Core vitals
    "hrv_sdnn":              ("hrv_sdnn",              "ms"),
    "resting_heart_rate":    ("resting_heart_rate",    "bpm"),
    "heart_rate":            ("heart_rate",            "bpm"),
    "spo2_pct":              ("spo2_pct",              "%"),
    "respiratory_rate":      ("respiratory_rate",      "bpm"),
    "bp_systolic":           ("bp_systolic",           "mmHg"),
    "bp_diastolic":          ("bp_diastolic",          "mmHg"),
    # Cardio / recovery
    "vo2_max":               ("vo2_max",               "mL/kg/min"),
    "walking_heart_rate_avg":("walking_heart_rate_avg","bpm"),
    "hr_recovery_1min":      ("hr_recovery_1min",      "bpm"),
    # Activity (unit-neutral)
    "step_count":            ("step_count",            "count"),
    "flights_climbed":       ("flights_climbed",       "count"),
    "active_energy_kcal":    ("active_energy_kcal",    "kcal"),
    "exercise_time_min":     ("exercise_time_min",     "min"),
    "stand_time_min":        ("stand_time_min",        "min"),
    # Gait — unit-neutral percentages
    "walking_asymmetry_pct":     ("walking_asymmetry_pct",     "%"),
    "walking_double_support_pct":("walking_double_support_pct","%"),
    # Body composition — unit-neutral
    "body_fat_pct":          ("body_fat_pct",          "%"),
    # Environment / mindfulness — unit-neutral
    "env_audio_dbspl":       ("env_audio_dbspl",       "dBASPL"),
    "headphone_audio_dbspl": ("headphone_audio_dbspl", "dBASPL"),
    "mindful_min":           ("mindful_min",           "min"),
    # Diet
    "dietary_energy_kcal":   ("dietary_energy_kcal",   "kcal"),
    "dietary_protein_g":     ("dietary_protein_g",     "g"),
    "dietary_carbs_g":       ("dietary_carbs_g",       "g"),
    "dietary_fat_g":         ("dietary_fat_g",         "g"),
    "dietary_fiber_g":       ("dietary_fiber_g",       "g"),
    "dietary_water_ml":      ("dietary_water_ml",      "mL"),
}

# Imperial keys Shortcuts sends on a US-locale iPhone → convert to SI for DB consistency
# DB always stores SI (matches XML importer). Display layer converts back to imperial.
_IMPERIAL_TO_SI: dict[str, tuple[str, str, float]] = {
    # shortcut key → (db metric, db unit, multiplier)
    "body_mass_lb":          ("body_mass_kg",          "kg",    0.453592),
    "lean_body_mass_lb":     ("lean_body_mass_kg",     "kg",    0.453592),
    "distance_walking_mi":   ("distance_walking_km",   "km",    1.60934),
    "walking_speed_mph":     ("walking_speed_m_s",     "m/s",   0.44704),
    "walking_step_length_in":("walking_step_length_m", "m",     0.0254),
    "stair_ascent_speed_fps":("stair_ascent_speed_m_s","m/s",   0.3048),
    "stair_descent_speed_fps":("stair_descent_speed_m_s","m/s", 0.3048),
    # Wrist temp: Shortcuts sends delta °F → store as delta °C (delta, so just multiply)
    "wrist_temp_delta_f":    ("wrist_temp_delta_c",    "°C",    0.5556),
}


@router.post("/apple/shortcut", dependencies=[Depends(_require_key)])
async def apple_shortcut_webhook(request: Request) -> dict[str, Any]:
    """Receive a flat metric payload from an Apple Shortcut and upsert into measurements.

    Payload shape:
        {
          "date": "2026-05-10T06:00:00-07:00",   // optional, defaults to now (UTC)
          "metrics": {
            "hrv_sdnn": 45.2,
            "resting_heart_rate": 58,
            "step_count": 8432,
            "active_energy_kcal": 520
          }
        }

    In the Shortcut, build a Dictionary action with a nested "metrics" Dictionary,
    then POST via "Get Contents of URL" with header X-SHC-Key.
    """
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc

    metrics: dict = data.get("metrics", {})
    if not isinstance(metrics, dict) or not metrics:
        raise HTTPException(status_code=400, detail="'metrics' dict is required and must be non-empty")

    ts_raw: str = data.get("date") or datetime.now(timezone.utc).isoformat()

    inserted = 0
    skipped: list[str] = []

    async with write_ctx() as conn:
        for shortcut_key, value in metrics.items():
            try:
                val = float(value)
            except (TypeError, ValueError):
                skipped.append(shortcut_key)
                continue

            if shortcut_key in _IMPERIAL_TO_SI:
                db_metric, db_unit, multiplier = _IMPERIAL_TO_SI[shortcut_key]
                val = round(val * multiplier, 4)
            elif shortcut_key in _SHORTCUT_UNITS:
                db_metric, db_unit = _SHORTCUT_UNITS[shortcut_key]
            else:
                skipped.append(shortcut_key)
                continue

            # Mindful sessions: Shortcuts returns duration in seconds, store as minutes
            if db_metric == "mindful_min" and val > 300:
                val = round(val / 60, 2)

            ext_id = f"shortcut:{db_metric}:{ts_raw}"
            row_hash = hashlib.sha256(f"{db_metric}{ts_raw}{val}".encode()).hexdigest()[:16]
            conn.execute(
                """
                INSERT INTO measurements
                    (source, metric, ts, value_num, unit, external_id, content_hash)
                VALUES ('apple_health', $metric, $ts, $value, $unit, $ext_id, $hash)
                ON CONFLICT (source, metric, ts, external_id) DO NOTHING
                """,
                {"metric": db_metric, "ts": ts_raw, "value": val, "unit": db_unit,
                 "ext_id": ext_id, "hash": row_hash},
            )
            inserted += 1

    log.info("Shortcut webhook: %d inserted, %d skipped (%s)", inserted, len(skipped), skipped)
    return {"ok": True, "inserted": inserted, "skipped": skipped}
