from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from xml.etree.ElementTree import iterparse

_OFFSET_RE = re.compile(r"\s+([+-])(\d{2})(\d{2})$")

from shc.db.schema import write_ctx

log = logging.getLogger(__name__)

# Apple Health XML type → (metric_name, unit_override)
_WANTED: dict[str, tuple[str, str | None]] = {
    "HKQuantityTypeIdentifierBodyMass": ("body_mass_kg", "kg"),
    "HKQuantityTypeIdentifierHeartRate": ("heart_rate", "bpm"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv_sdnn", "ms"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_heart_rate", "bpm"),
    "HKQuantityTypeIdentifierStepCount": ("step_count", "count"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierBasalEnergyBurned": ("basal_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierOxygenSaturation": ("spo2_pct", "%"),
    "HKQuantityTypeIdentifierRespiratoryRate": ("respiratory_rate", "bpm"),
    "HKQuantityTypeIdentifierBloodPressureSystolic": ("bp_systolic", "mmHg"),
    "HKQuantityTypeIdentifierBloodPressureDiastolic": ("bp_diastolic", "mmHg"),
    "HKQuantityTypeIdentifierBodyFatPercentage": ("body_fat_pct", "%"),
    "HKQuantityTypeIdentifierVO2Max": ("vo2_max", "mL/kg/min"),
    "HKQuantityTypeIdentifierFlightsClimbed": ("flights_climbed", "count"),
}

_KG_TYPES = {"HKQuantityTypeIdentifierBodyMass"}
_LB_TO_KG = 0.453592

# Apple workout type suffix → cardio modality. Strength types deliberately absent — skip those.
_WORKOUT_MODALITY: dict[str, str] = {
    "Walking": "walk",
    "Running": "run",
    "Cycling": "bike",
    "Hiking": "hike",
    "Swimming": "swim",
    "Pickleball": "pickleball",
    "Tennis": "tennis",
    "Yoga": "yoga",
    "Dance": "other",
    "MixedCardio": "other",
    "CrossTraining": "other",
    "Rowing": "other",
    "Elliptical": "other",
    "StairClimbing": "other",
    "PaddleSports": "other",
    "Barre": "yoga",
    "Pilates": "yoga",
}
# Types to silently skip — don't log them as cardio
_SKIP_WORKOUT_TYPES = {
    "TraditionalStrengthTraining",
    "FunctionalStrengthTraining",
    "CoreTraining",
    "Flexibility",
    "Mindfulness",
    "Meditation",
}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _norm_ts(raw: str) -> str:
    """'2023-01-15 08:30:00 -0700' → '2023-01-15 08:30:00-07:00'"""
    return _OFFSET_RE.sub(r"\1\2:\3", raw.strip())


def _to_kg(value: float, unit: str) -> float:
    if unit == "lb":
        return round(value * _LB_TO_KG, 3)
    return value


def _workout_modality(activity_type: str) -> str | None:
    """Return cardio modality for a HKWorkoutActivityType string, or None to skip."""
    # Strip prefix: 'HKWorkoutActivityTypeWalking' → 'Walking'
    suffix = activity_type.removeprefix("HKWorkoutActivityType")
    if suffix in _SKIP_WORKOUT_TYPES:
        return None
    return _WORKOUT_MODALITY.get(suffix, "other")


def _workout_avg_hr(elem) -> int | None:
    """Extract average heart rate from WorkoutStatistics child elements."""
    for stat in elem.findall("WorkoutStatistics"):
        if stat.get("type") == "HKQuantityTypeIdentifierHeartRate":
            avg = stat.get("average")
            try:
                return round(float(avg)) if avg else None
            except (ValueError, TypeError):
                pass
    return None


async def ingest_export(path: Path, batch_size: int = 500) -> dict[str, int]:
    """Stream Apple Health export.xml and import wanted metric types + workouts."""
    counts: dict[str, int] = {}
    batch: list[dict] = []
    workout_rows: list[dict] = []

    async def _flush_measurements(conn) -> None:
        for row in batch:
            conn.execute(
                """
                INSERT INTO measurements
                    (source, metric, ts, value_num, unit, external_id, content_hash)
                VALUES ('apple_health', $metric, $ts, $value, $unit, $ext_id, $hash)
                ON CONFLICT (source, metric, ts, external_id) DO NOTHING
                """,
                row,
            )
        batch.clear()

    async def _flush_workouts(conn) -> None:
        for row in workout_rows:
            conn.execute(
                """
                INSERT INTO cardio_sessions
                    (id, date, modality, duration_min, avg_hr, rpe, zone_distribution_json, content_hash)
                VALUES ($id, $date, $modality, $dur, $hr, NULL, NULL, $hash)
                ON CONFLICT (id) DO NOTHING
                """,
                row,
            )
        workout_rows.clear()

    log.info("streaming Apple Health XML from %s (this may take several minutes)", path)
    context = iterparse(str(path), events=("end",))

    async with write_ctx() as conn:
        for _event, elem in context:
            if elem.tag == "Workout":
                activity_type = elem.get("workoutActivityType", "")
                modality = _workout_modality(activity_type)
                if modality is not None:
                    start = _norm_ts(elem.get("startDate", ""))
                    date_part = start[:10]  # 'YYYY-MM-DD'
                    dur_raw = elem.get("duration")
                    dur_unit = elem.get("durationUnit", "min")
                    try:
                        dur_f = float(dur_raw) if dur_raw else None
                        # Apple usually stores minutes, but handle seconds just in case
                        if dur_f and dur_unit == "s":
                            dur_f = dur_f / 60
                        dur_min = round(dur_f) if dur_f else None
                    except (ValueError, TypeError):
                        dur_min = None

                    avg_hr = _workout_avg_hr(elem)
                    ext_id = f"apple_workout:{activity_type}:{start}"
                    row = {
                        "id": _h(ext_id),
                        "date": date_part,
                        "modality": modality,
                        "dur": dur_min,
                        "hr": avg_hr,
                        "hash": _h(ext_id),
                    }
                    workout_rows.append(row)
                    counts["_workouts"] = counts.get("_workouts", 0) + 1

                    if len(workout_rows) >= batch_size:
                        await _flush_workouts(conn)

                elem.clear()
                continue

            if elem.tag != "Record":
                elem.clear()
                continue

            rtype = elem.get("type", "")
            if rtype not in _WANTED:
                elem.clear()
                continue

            metric_name, unit_override = _WANTED[rtype]
            raw_val = elem.get("value", "")
            ts = _norm_ts(elem.get("startDate") or elem.get("creationDate", ""))
            raw_unit = elem.get("unit", "")

            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                elem.clear()
                continue

            if rtype in _KG_TYPES:
                val = _to_kg(val, raw_unit)

            unit = unit_override or raw_unit
            ext_id = f"apple:{rtype}:{ts}"
            batch.append({
                "metric": metric_name,
                "ts": ts,
                "value": val,
                "unit": unit,
                "ext_id": ext_id,
                "hash": _h(ext_id),
            })
            counts[metric_name] = counts.get(metric_name, 0) + 1

            if len(batch) >= batch_size:
                await _flush_measurements(conn)

            elem.clear()

        if batch:
            await _flush_measurements(conn)
        if workout_rows:
            await _flush_workouts(conn)

    log.info("Apple Health XML import complete: %s", counts)
    return counts
