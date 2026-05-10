from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from defusedxml.ElementTree import iterparse

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
    # Body composition — populated by smart scales via Apple Health
    "HKQuantityTypeIdentifierLeanBodyMass": ("lean_body_mass_kg", "kg"),
    # Cardio / recovery
    "HKQuantityTypeIdentifierWalkingHeartRateAverage": ("walking_heart_rate_avg", "bpm"),
    "HKQuantityTypeIdentifierHeartRateRecoveryOneMinute": ("hr_recovery_1min", "bpm"),
    # Gait & mobility (Apple Watch accelerometer — outdoor walks)
    "HKQuantityTypeIdentifierWalkingSpeed": ("walking_speed_m_s", "m/s"),
    "HKQuantityTypeIdentifierWalkingStepLength": ("walking_step_length_m", "m"),
    "HKQuantityTypeIdentifierWalkingAsymmetryPercentage": ("walking_asymmetry_pct", "%"),
    "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage": ("walking_double_support_pct", "%"),
    "HKQuantityTypeIdentifierStairAscentSpeed": ("stair_ascent_speed_m_s", "m/s"),
    "HKQuantityTypeIdentifierStairDescentSpeed": ("stair_descent_speed_m_s", "m/s"),
    # Activity rings
    "HKQuantityTypeIdentifierAppleExerciseTime": ("exercise_time_min", "min"),
    "HKQuantityTypeIdentifierAppleStandTime": ("stand_time_min", "min"),
    # Distance
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance_walking_km", "km"),
    # Body / environment
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": ("wrist_temp_delta_c", "°C"),
    "HKQuantityTypeIdentifierEnvironmentalAudioExposure": ("env_audio_dbspl", "dBASPL"),
    "HKQuantityTypeIdentifierHeadphoneAudioExposure": ("headphone_audio_dbspl", "dBASPL"),
    # Fueling / diet — populated by MyFitnessPal, Cronometer, Lose-It, etc.
    "HKQuantityTypeIdentifierDietaryEnergyConsumed": ("dietary_energy_kcal", "kcal"),
    "HKQuantityTypeIdentifierDietaryProtein": ("dietary_protein_g", "g"),
    "HKQuantityTypeIdentifierDietaryCarbohydrates": ("dietary_carbs_g", "g"),
    "HKQuantityTypeIdentifierDietaryFatTotal": ("dietary_fat_g", "g"),
    "HKQuantityTypeIdentifierDietaryFiber": ("dietary_fiber_g", "g"),
    "HKQuantityTypeIdentifierDietarySugar": ("dietary_sugar_g", "g"),
    "HKQuantityTypeIdentifierDietaryWater": ("dietary_water_ml", "mL"),
    "HKQuantityTypeIdentifierDietarySodium": ("dietary_sodium_mg", "mg"),
    "HKQuantityTypeIdentifierDietaryCaffeine": ("dietary_caffeine_mg", "mg"),
}


_KG_TYPES = {"HKQuantityTypeIdentifierBodyMass", "HKQuantityTypeIdentifierLeanBodyMass"}
_LB_TO_KG = 0.453592


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _norm_ts(raw: str) -> str:
    """'2023-01-15 08:30:00 -0700' → '2023-01-15 08:30:00-07:00'"""
    return _OFFSET_RE.sub(r"\1\2:\3", raw.strip())


def _to_kg(value: float, unit: str) -> float:
    if unit == "lb":
        return round(value * _LB_TO_KG, 3)
    return value


async def ingest_export(path: Path, batch_size: int = 500) -> dict[str, int]:
    """Stream Apple Health export.xml and import wanted metric types.

    Workout/activity elements are skipped — WHOOP handles cardio tracking
    and mirrors sessions into cardio_sessions via the API sync.
    """
    counts: dict[str, int] = {}
    batch: list[dict] = []

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

    log.info("streaming Apple Health XML from %s (this may take several minutes)", path)
    context = iterparse(str(path), events=("end",))

    async with write_ctx() as conn:
        for _event, elem in context:
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

    log.info("Apple Health XML import complete: %s", counts)
    return counts
