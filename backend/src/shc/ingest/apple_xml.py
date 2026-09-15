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
    "HKQuantityTypeIdentifierBodyMassIndex": ("body_mass_index", "kg/m²"),
    "HKQuantityTypeIdentifierVO2Max": ("vo2_max", "mL/kg/min"),
    "HKQuantityTypeIdentifierFlightsClimbed": ("flights_climbed", "count"),
    # Effort / light exposure (large-volume Watch metrics, not previously mapped)
    "HKQuantityTypeIdentifierPhysicalEffort": ("physical_effort", "kcal/hr·kg"),
    "HKQuantityTypeIdentifierTimeInDaylight": ("time_in_daylight_min", "min"),
    # Fall-risk / cardiorespiratory fitness — low volume, high signal
    "HKQuantityTypeIdentifierAppleWalkingSteadiness": ("walking_steadiness_pct", "%"),
    "HKQuantityTypeIdentifierSixMinuteWalkTestDistance": ("six_min_walk_test_m", "m"),
    "HKQuantityTypeIdentifierHeight": ("height_cm", "cm"),
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
_FT_TYPES = {"HKQuantityTypeIdentifierHeight"}
_FT_TO_CM = 30.48

# Apple's XML export stores every HealthKit percentUnit field (unit="%") as a
# fraction of 1, not a number out of 100 — verified 2026-09-14 against ingested
# samples, whose values sat two orders of magnitude below their plausible
# physiological range. Every "%"-unit type must be multiplied by 100 at ingest,
# or it silently reads 100x low downstream (dashboard.py's 28d
# walking-asymmetry note would render a fraction where a percentage belongs).
# Applies uniformly to every _WANTED type carrying unit "%" (spo2_pct,
# walking_asymmetry_pct, walking_double_support_pct, walking_steadiness_pct,
# body_fat_pct).

# Category (interval) types handled outside the quantity `_WANTED` table —
# value is a string enum, not a float, and duration comes from start/end
# rather than a `value=` attribute. Stored as its own `apple_health` metric,
# deliberately namespaced apart from the `sleep` table WHOOP populates —
# DailyState's sleep numbers must stay WHOOP-sourced per CLAUDE.md; this is
# supplementary (and, pre-2023, the only sleep signal that exists at all).
_SLEEP_STAGE_VALUES = {
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisAsleepCore": "asleep_core",
    "HKCategoryValueSleepAnalysisAsleepDeep": "asleep_deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "asleep_rem",
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


def _duration_min(start: str, end: str) -> float | None:
    from datetime import datetime

    try:
        s = datetime.fromisoformat(_norm_ts(start))
        e = datetime.fromisoformat(_norm_ts(end))
    except ValueError:
        return None
    return round((e - s).total_seconds() / 60, 2)


_STAGING_TABLE = "_apple_xml_staging"


async def ingest_export(path: Path, batch_size: int = 50_000) -> dict[str, int]:
    """Stream Apple Health export.xml and import wanted metric + sleep-stage types.

    Workout/activity elements are skipped — WHOOP handles cardio tracking
    and mirrors sessions into cardio_sessions via the API sync. Sleep-stage
    category records are imported as a distinct `sleep_stage_apple` metric,
    not written into the `sleep` table WHOOP owns — see module docstring.

    Bulk-loads each batch into an unconstrained temp staging table, then does
    ONE set-based anti-join INSERT against `measurements` per batch, instead
    of per-row inserts against the live composite PRIMARY KEY. Measured
    2026-09-14: per-row inserts against the already-populated table ran at
    roughly 500 rows/0.95s (~2+ hours for this file's ~4.2M records) — DuckDB
    is a columnar engine, and incremental single/small-batch constraint
    checks against a multi-million-row index are the wrong shape for it. The
    anti-join pattern turns millions of point lookups into one hash join per
    batch, which is what the engine is actually built for.
    """
    import time

    counts: dict[str, int] = {}
    batch: list[tuple] = []
    total_flushed = 0
    t_start = time.time()

    async def _flush(conn) -> None:
        nonlocal total_flushed
        if not batch:
            return
        conn.execute(f"DELETE FROM {_STAGING_TABLE}")
        conn.executemany(
            f"INSERT INTO {_STAGING_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        conn.execute(
            f"""
            INSERT INTO measurements
                (source, metric, ts, value_num, value_text, unit, external_id, content_hash)
            SELECT s.source, s.metric, s.ts, s.value_num, s.value_text, s.unit,
                   s.external_id, s.content_hash
            FROM (
                -- Two Apple sources (e.g. Watch + Clock app) can both report a
                -- record with the identical (source, metric, ts, external_id)
                -- key within one batch — the old per-row ON CONFLICT DO NOTHING
                -- handled this for free since each row was a separate committed
                -- statement; this batch approach needs the dedup made explicit,
                -- or the second occurrence collides on insert. Confirmed
                -- 2026-09-14: crashed 4.25M rows into this exact file.
                SELECT DISTINCT ON (source, metric, ts, external_id) *
                FROM {_STAGING_TABLE}
            ) s
            WHERE NOT EXISTS (
                SELECT 1 FROM measurements m
                WHERE m.source = s.source AND m.metric = s.metric
                  AND m.ts = s.ts AND m.external_id = s.external_id
            )
            """
        )
        total_flushed += len(batch)
        elapsed = time.time() - t_start
        log.info(
            "Apple Health XML import: %d rows flushed (%.0f rows/sec, %.1fs elapsed)",
            total_flushed,
            total_flushed / elapsed if elapsed > 0 else 0,
            elapsed,
        )
        batch.clear()

    log.info("streaming Apple Health XML from %s", path)
    context = iterparse(str(path), events=("end",))

    async with write_ctx() as conn:
        conn.execute(
            f"""
            CREATE TEMP TABLE IF NOT EXISTS {_STAGING_TABLE} (
                source VARCHAR, metric VARCHAR, ts TIMESTAMPTZ, value_num DOUBLE,
                value_text VARCHAR, unit VARCHAR, external_id VARCHAR, content_hash VARCHAR
            )
            """
        )
        conn.execute(f"DELETE FROM {_STAGING_TABLE}")

        for _event, elem in context:
            if elem.tag != "Record":
                elem.clear()
                continue

            rtype = elem.get("type", "")

            if rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                raw_stage = elem.get("value", "")
                stage = _SLEEP_STAGE_VALUES.get(raw_stage, raw_stage)
                start = elem.get("startDate") or elem.get("creationDate", "")
                end = elem.get("endDate") or start
                ts = _norm_ts(start)
                dur = _duration_min(start, end)
                ext_id = f"apple:{rtype}:{ts}"
                batch.append((
                    "apple_health", "sleep_stage_apple", ts, dur, stage, "min",
                    ext_id, _h(ext_id),
                ))
                counts["sleep_stage_apple"] = counts.get("sleep_stage_apple", 0) + 1
                if len(batch) >= batch_size:
                    await _flush(conn)
                elem.clear()
                continue

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
            elif rtype in _FT_TYPES:
                val = round(val * _FT_TO_CM, 2)
            elif raw_unit == "%":
                # Apple stores percentUnit fields as a 0-1 fraction — see the
                # module-level note above _SLEEP_STAGE_VALUES.
                val = round(val * 100, 4)

            unit = unit_override or raw_unit
            ext_id = f"apple:{rtype}:{ts}"
            batch.append((
                "apple_health", metric_name, ts, val, None, unit, ext_id, _h(ext_id),
            ))
            counts[metric_name] = counts.get(metric_name, 0) + 1

            if len(batch) >= batch_size:
                await _flush(conn)

            elem.clear()

        await _flush(conn)
        conn.execute(f"DROP TABLE IF EXISTS {_STAGING_TABLE}")

    log.info("Apple Health XML import complete: %s", counts)
    return counts
