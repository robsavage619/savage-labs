from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

from watchdog.events import FileClosedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from shc.config import settings
from shc.db.schema import write_ctx

log = logging.getLogger(__name__)

_DEBOUNCE_S = 2.0
_SIZE_STABLE_S = 1.0


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _size_stable(path: Path) -> bool:
    """Return True if file size hasn't changed in _SIZE_STABLE_S seconds."""
    s1 = path.stat().st_size
    time.sleep(_SIZE_STABLE_S)
    s2 = path.stat().st_size
    return s1 == s2


class _HAEHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._pending: dict[str, asyncio.TimerHandle] = {}

    def on_closed(self, event: FileClosedEvent) -> None:  # type: ignore[override]
        path = Path(event.src_path)
        if path.suffix.lower() not in (".json", ".csv"):
            return
        key = str(path)
        if key in self._pending:
            self._pending[key].cancel()
        handle = self._loop.call_later(_DEBOUNCE_S, self._process, path)
        self._pending[key] = handle

    def _process(self, path: Path) -> None:
        self._pending.pop(str(path), None)
        asyncio.run_coroutine_threadsafe(_ingest_file(path), self._loop)


async def _ingest_file(path: Path) -> None:
    if not path.exists():
        return
    if not _size_stable(path):
        log.warning("HAE file %s still growing, skipping", path.name)
        return

    processing_dir = settings.data_dir / "hae_processing"
    processing_dir.mkdir(parents=True, exist_ok=True)
    dest = processing_dir / path.name
    shutil.move(str(path), dest)

    try:
        raw = dest.read_bytes()
        content_hash = _hash_bytes(raw)
        data = json.loads(raw)
        await _store_hae(data, content_hash)
        log.info("ingested HAE file %s", path.name)
        dest.unlink(missing_ok=True)
    except json.JSONDecodeError:
        log.exception("failed to parse HAE file %s — left in processing dir for inspection", dest)
    except Exception:
        log.exception("HAE ingest failed for %s — left in processing dir for inspection", dest)


# HAE export → canonical DB metric name.
# HAE sends Health app display strings; all other paths use our snake_case keys.
_HAE_METRIC_MAP: dict[str, str] = {
    "Heart Rate Variability": "hrv_sdnn",
    "Heart Rate Variability (SDNN)": "hrv_sdnn",
    "Resting Heart Rate": "resting_heart_rate",
    "Heart Rate": "heart_rate",
    "Blood Oxygen Saturation": "spo2_pct",
    "Oxygen Saturation": "spo2_pct",
    "Respiratory Rate": "respiratory_rate",
    "Step Count": "step_count",
    "Active Energy": "active_energy_kcal",
    "Active Energy Burned": "active_energy_kcal",
    "Basal Energy": "basal_energy_kcal",
    "Basal Energy Burned": "basal_energy_kcal",
    "Flights Climbed": "flights_climbed",
    "Stand Time": "stand_time_min",
    "Stand Hours": "stand_time_min",
    "Exercise Time": "exercise_time_min",
    "Exercise Minutes": "exercise_time_min",
    "Mindful Minutes": "mindful_min",
    "Mindfulness": "mindful_min",
    "Walking Heart Rate Average": "walking_heart_rate_avg",
    "Environmental Audio Exposure": "env_audio_dbspl",
    "Headphone Audio Exposure": "headphone_audio_dbspl",
    "Walking Asymmetry Percentage": "walking_asymmetry_pct",
    "Walking Double Support Percentage": "walking_double_support_pct",
    "Walking + Running Distance": "distance_walking_km",
    "Walking Speed": "walking_speed_m_s",
    "Walking Step Length": "walking_step_length_m",
    "Stair Speed: Ascent": "stair_ascent_speed_m_s",
    "Stair Speed: Descent": "stair_descent_speed_m_s",
    "Wrist Temperature": "wrist_temp_delta_c",
    "Body Weight": "body_mass_kg",
    "Weight Body Mass": "body_mass_kg",
    "Body Mass Index": "body_mass_index",
    "Body Fat Percentage": "body_fat_pct",
    "Lean Body Mass": "lean_body_mass_kg",
    "Blood Pressure Systolic": "bp_systolic",
    "Blood Pressure Diastolic": "bp_diastolic",
}

# HAE sends values in the iPhone locale's preferred units (US = imperial).
# (canonical_metric, hae_unit) → (db_unit, multiplier)
_HAE_UNIT_CONV: dict[tuple[str, str], tuple[str, float]] = {
    ("distance_walking_km", "mi"): ("km", 1.60934),
    ("distance_walking_km", "mile"): ("km", 1.60934),
    ("walking_speed_m_s", "mph"): ("m/s", 0.44704),
    ("walking_step_length_m", "in"): ("m", 0.0254),
    ("stair_ascent_speed_m_s", "ft/s"): ("m/s", 0.3048),
    ("stair_descent_speed_m_s", "ft/s"): ("m/s", 0.3048),
    ("body_mass_kg", "lb"): ("kg", 0.453592),
    ("lean_body_mass_kg", "lb"): ("kg", 0.453592),
    # Wrist temp is a delta; multiply °F delta → °C delta (not subtract 32)
    ("wrist_temp_delta_c", "°F"): ("°C", 0.5556),
}


async def _store_hae(data: dict, content_hash: str) -> None:
    """Parse HealthAutoExport JSON and upsert into measurements."""
    metrics = data.get("data", {})
    if not isinstance(metrics, dict):
        return

    async with write_ctx() as conn:
        for metric_name, entries in metrics.items():
            if not isinstance(entries, list):
                continue
            canonical = _HAE_METRIC_MAP.get(metric_name)
            if canonical is None:
                log.debug("HAE: unmapped metric %r — skipping", metric_name)
                continue
            for entry in entries:
                ts = entry.get("date") or entry.get("startDate")
                raw_value = entry.get("qty") or entry.get("value")
                hae_unit = entry.get("units", "")
                if ts is None or raw_value is None:
                    continue
                # Apply unit conversion when HAE sends imperial values.
                conv = _HAE_UNIT_CONV.get((canonical, hae_unit))
                if conv:
                    db_unit, multiplier = conv
                    value = float(raw_value) * multiplier
                else:
                    db_unit = hae_unit
                    value = float(raw_value) if isinstance(raw_value, (int, float, str)) else None
                if value is None:
                    continue
                external_id = f"hae:{canonical}:{ts}"
                row_hash = hashlib.sha256(f"{canonical}{ts}{value}".encode()).hexdigest()[:16]
                conn.execute(
                    """
                    INSERT INTO measurements
                        (source, metric, ts, value_num, unit, external_id, content_hash)
                    VALUES ('apple_health', $metric, $ts, $value, $unit, $ext_id, $hash)
                    ON CONFLICT (source, metric, ts, external_id) DO NOTHING
                    """,
                    {
                        "metric": canonical,
                        "ts": ts,
                        "value": value,
                        "unit": db_unit,
                        "ext_id": external_id,
                        "hash": row_hash,
                    },
                )


_observer: Observer | None = None


def start_watcher(loop: asyncio.AbstractEventLoop) -> None:
    global _observer
    watch_dir = settings.hae_dir
    watch_dir.mkdir(parents=True, exist_ok=True)
    handler = _HAEHandler(loop)
    _observer = Observer()
    _observer.schedule(handler, str(watch_dir), recursive=False)
    _observer.start()
    log.info("watching HAE folder %s", watch_dir)


def stop_watcher() -> None:
    if _observer:
        _observer.stop()
        _observer.join()
