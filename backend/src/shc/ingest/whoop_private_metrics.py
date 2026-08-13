"""Ingest for WHOOP signals that have no public-API equivalent.

Covers four surfaces, all reached through `whoop_private.get`:

* **Sleep need + optimal window** — WHOOP's recommended bedtime window, which is
  the target Rob's midpoint variability should actually be measured against.
* **Stress monitor** — a per-sample autonomic curve the public API omits
  entirely. WHOOP's own impact analysis attributes -5% recovery to time spent
  in the high-stress zone, so it is not decorative.
* **Behavior impact** — WHOOP's server-side correlations, computed over full
  history. The `AUTOMATED` ones are metric-derived and populate without any
  journal data.
* **HR zones** — the boundaries WHOOP used to compute the zone minutes already
  stored in `cardio_sessions`.

Values are lifted from BFF payloads, which are UI trees. Where a number is only
available as a rendered string (`"1.8"`, `"0:30"`) it is parsed defensively and
a miss yields None rather than a wrong number — a silently-wrong metric is
worse here than a missing one.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# Stress-curve clock labels are local wall time, matching `ingest.whoop`'s
# fallback zone. Stamping them UTC shifts the whole curve by the offset.
_LOCAL_TZ = ZoneInfo("America/Los_Angeles")

_MS_PER_MIN = 60_000.0

_SLEEP_NEED_PATH = "/coaching-service/v2/sleepneed"
_STRESS_PATH = "/health-service/v2/stress-bff/{date}"
_IMPACT_PATH = "/behavior-impact-service/v1/impact"
_ZONES_PATH = "/hr-zones-service/v1/bff/zones"
_SLEEP_HR_BASELINE_PATH = "/sleep-service/v1/heart-rate/baseline"


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _ms_to_min(ms: Any) -> float | None:
    """Convert a millisecond figure to minutes, or None if not numeric."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    return round(ms / _MS_PER_MIN, 1)


def _num(text: Any) -> float | None:
    """Parse a rendered numeric string ("1.8", "+10%", "-5%") to a float."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    if not isinstance(text, str):
        return None
    cleaned = text.strip().replace("%", "").replace("+", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _clock_to_time(text: Any) -> tuple[int, int] | None:
    """Parse a rendered clock label ("12:49 AM", "23:25:00") to (hour, minute)."""
    if not isinstance(text, str):
        return None
    raw = text.strip().upper()
    meridiem = None
    for suffix in ("AM", "PM"):
        if raw.endswith(suffix):
            meridiem, raw = suffix, raw[: -len(suffix)].strip()
            break
    bits = raw.split(":")
    if len(bits) < 2:
        return None
    try:
        hour, minute = int(bits[0]), int(bits[1])
    except ValueError:
        return None
    if meridiem == "AM" and hour == 12:
        hour = 0
    elif meridiem == "PM" and hour != 12:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _walk(node: Any, key: str, found: list[Any], depth: int = 0) -> None:
    """Collect every value stored under `key` anywhere in a BFF tree."""
    if depth > 12:
        return
    if isinstance(node, dict):
        if key in node:
            found.append(node[key])
        for value in node.values():
            _walk(value, key, found, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _walk(value, key, found, depth + 1)


async def sync_sleep_need() -> dict:
    """Pull the sleep-need breakdown and WHOOP's recommended sleep window."""
    from shc.ingest.whoop_private import get

    payload = await get(_SLEEP_NEED_PATH)
    breakdown = payload.get("need_breakdown") or {}
    # The tiered block lives under `recommended_time_in_bed_formatted`, NOT
    # `need_breakdown_formatted` (which is a rendered narrative string) — the
    # near-identical names cost a silent round of all-None windows.
    formatted = payload.get("recommended_time_in_bed_formatted") or {}
    # Keyed by sleep-performance target ("100", "85", "70",
    # "optimize_sleep"); 100 is the one worth storing as the target.
    tier = formatted.get("100") or {}
    endpoints = tier.get("optimal_endpoints_formatted") or {}

    return {
        "need_total_min": _ms_to_min(breakdown.get("total")),
        "need_baseline_min": _ms_to_min(breakdown.get("baseline")),
        "need_strain_min": _ms_to_min(breakdown.get("strain")),
        "need_debt_min": _ms_to_min(breakdown.get("debt")),
        "need_nap_min": _ms_to_min(breakdown.get("naps")),
        "optimal_bedtime_start": endpoints.get("start"),
        "optimal_bedtime_end": endpoints.get("end"),
        "recommended_tib_min": _ms_to_min(tier.get("recommended_time_in_bed")),
    }


async def sync_sleeping_hr_baseline() -> float | None:
    """Fetch the sleeping-HR baseline (a bare float, not an object)."""
    from shc.ingest.whoop_private import get

    value = await get(_SLEEP_HR_BASELINE_PATH)
    if isinstance(value, dict):  # tolerate a future wrap
        value = value.get("sleeping_hr_baseline")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _stress_samples(payload: dict, day: _date) -> list[tuple[datetime, float | None, str | None]]:
    """Reconstruct the stress curve from the 24-hour graph's scrubber details.

    Each point's real value rides in `data_scrubber_details.value_display` with
    its clock time in `primary_contextual_display`; the `position_x/y` fields
    are normalised UI coordinates and are deliberately ignored.

    Two things the labels do not tell you, both of which silently shift every
    sample if assumed away:

    * The clock label is **local wall time**, not UTC. Stamping "12:49 AM" as
      UTC moved the whole curve by the offset (7h in Pacific), which reads as
      plausible data on the wrong hour.
    * The window is a rolling 24h that **starts the previous evening** and ends
      on `day`. Anchoring the roll-forward at the series start therefore dated
      everything a day late — the fix anchors on the END, which is the point
      the API guarantees belongs to `day`.
    """
    scrubbers: list[Any] = []
    _walk(payload.get("extended24_hour_graph"), "data_scrubber_details", scrubbers)

    samples: list[tuple[datetime, float | None, str | None]] = []
    current = day
    previous_minutes: int | None = None
    for detail in scrubbers:
        if not isinstance(detail, dict):
            continue
        clock = _clock_to_time(detail.get("primary_contextual_display"))
        if clock is None:
            continue
        hour, minute = clock
        minutes = hour * 60 + minute
        if previous_minutes is not None and minutes < previous_minutes:
            current = current + timedelta(days=1)
        previous_minutes = minutes
        samples.append(
            (
                datetime(current.year, current.month, current.day, hour, minute, tzinfo=_LOCAL_TZ),
                _num(detail.get("value_display")),
                detail.get("secondary_contextual_display"),
            )
        )

    if samples:
        # The window is not a fixed frame: a completed day comes back as a
        # calendar window (00:04 -> next 00:54), while the current day comes
        # back as a rolling 24h ending now (20:44 yesterday -> 20:34 today).
        # Anchoring on either endpoint is right for one shape and a full day
        # wrong for the other, so pick the whole-series shift that puts the
        # most samples on `day` and let the data settle it.
        best = max(
            (-1, 0, 1),
            key=lambda shift: sum(
                1 for stamp, _, _ in samples if (stamp + timedelta(days=shift)).date() == day
            ),
        )
        if best:
            samples = [(stamp + timedelta(days=best), v, lvl) for stamp, v, lvl in samples]
    return samples


async def sync_stress(day: _date) -> dict:
    """Pull the stress gauge plus the day's sampled stress curve."""
    from shc.ingest.whoop_private import get

    payload = await get(_STRESS_PATH.format(date=day.isoformat()))
    gauge = payload.get("gauge") or {}
    samples = _stress_samples(payload, day)

    levelled = [level for _, _, level in samples if level]
    high_pct = (
        round(sum(1 for level in levelled if level.upper() == "HIGH") / len(levelled), 4)
        if levelled
        else None
    )

    return {
        "stress_score": _num(gauge.get("gauge_score_display")),
        "stress_level": gauge.get("gauge_subtext_display"),
        "stress_state": payload.get("stress_state"),
        "stress_high_pct": high_pct,
        "samples": samples,
    }


async def sync_behavior_impact() -> list[dict]:
    """Pull WHOOP's server-side behavior/metric impact analysis."""
    from shc.ingest.whoop_private import get

    payload = await get(_IMPACT_PATH)
    cards: list[Any] = []
    # Tiles are BFF envelopes ({type, content}); the cards sit under `content`,
    # so walking for the key is more durable than indexing the envelope.
    _walk(payload.get("tiles"), "impact_cards", cards)

    rows: list[dict] = []
    for group in cards:
        if not isinstance(group, list):
            continue
        for card in group:
            if not isinstance(card, dict) or not card.get("impact_uuid"):
                continue
            tags = card.get("tile_tags") or []
            rows.append(
                {
                    "impact_uuid": card["impact_uuid"],
                    "title": card.get("impact_card_title_display") or "",
                    "impact_pct": _num(card.get("impact_percentage_display")),
                    "impact_style": card.get("impact_style"),
                    "tag_style": (tags[0].get("tag_style") if tags else None),
                    "yes_count": _answer_count(card.get("yes_answer_count")),
                    "no_count": _answer_count(card.get("no_answer_count")),
                }
            )
    return rows


def _answer_count(raw: Any) -> int | None:
    """Answer counts arrive either bare or wrapped in a display object."""
    if isinstance(raw, dict):
        raw = raw.get("answer_count_text_display")
    value = _num(raw)
    return int(value) if value is not None else None


async def sync_hr_zones() -> list[dict]:
    """Pull the zone boundaries WHOOP used to compute stored zone minutes."""
    from shc.ingest.whoop_private import get

    payload = await get(_ZONES_PATH)
    zones = payload.get("zones") or []
    entry = payload.get("max_hr_entry_field") or {}
    max_hr = _num(entry.get("value")) if isinstance(entry, dict) else None
    # `max_hr_entry_field` is null unless the user typed a custom max, so fall
    # back to the top of the highest zone — which is the max HR by construction.
    if max_hr is None and zones:
        max_hr = _num(max(z.get("max") or 0 for z in zones))

    return [
        {
            "zone_id": z.get("id"),
            "min_bpm": z.get("min"),
            "max_bpm": z.get("max"),
            "max_hr": int(max_hr) if max_hr else None,
            "effective_at": payload.get("effective_timestamp"),
        }
        for z in zones
        if z.get("id")
    ]


async def sync_private_metrics(days: int = 7) -> dict:
    """Pull every private-API metric surface and persist it.

    Sleep need, HR zones and behavior impact are point-in-time views (WHOOP
    serves the current computation, not a per-date history), so they are stored
    against today. Stress is genuinely per-date and is walked back `days`.
    """
    from shc.db.schema import write_ctx

    # Local date, not UTC: after ~17:00 Pacific the UTC date is already
    # tomorrow, which filed a whole day of metrics under a date that had not
    # happened yet and left the real day without its sleep-need row.
    today = datetime.now(_LOCAL_TZ).date()
    failures: list[str] = []

    async def _attempt(label: str, coro: Any) -> Any:
        try:
            return await coro
        except Exception as exc:  # isolate per surface — one failure isn't fatal
            log.warning("WHOOP private metric %s failed: %s", label, exc)
            failures.append(label)
            return None

    need = await _attempt("sleep_need", sync_sleep_need()) or {}
    baseline = await _attempt("sleeping_hr_baseline", sync_sleeping_hr_baseline())
    zones = await _attempt("hr_zones", sync_hr_zones()) or []
    impacts = await _attempt("behavior_impact", sync_behavior_impact()) or []

    stress_days = 0
    timeline_rows = 0

    async with write_ctx() as conn:
        for zone in zones:
            conn.execute(
                """
                INSERT INTO whoop_hr_zones
                    (zone_id, min_bpm, max_bpm, max_hr, effective_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (zone_id) DO UPDATE SET
                    min_bpm      = EXCLUDED.min_bpm,
                    max_bpm      = EXCLUDED.max_bpm,
                    max_hr       = EXCLUDED.max_hr,
                    effective_at = EXCLUDED.effective_at,
                    fetched_at   = EXCLUDED.fetched_at
                """,
                [
                    zone["zone_id"],
                    zone["min_bpm"],
                    zone["max_bpm"],
                    zone["max_hr"],
                    zone["effective_at"],
                    datetime.now(UTC),
                ],
            )

        for row in impacts:
            conn.execute(
                """
                INSERT INTO whoop_behavior_impact
                    (as_of, impact_uuid, title, impact_pct, impact_style, tag_style,
                     yes_count, no_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (as_of, impact_uuid) DO UPDATE SET
                    title        = EXCLUDED.title,
                    impact_pct   = EXCLUDED.impact_pct,
                    impact_style = EXCLUDED.impact_style,
                    tag_style    = EXCLUDED.tag_style,
                    yes_count    = EXCLUDED.yes_count,
                    no_count     = EXCLUDED.no_count
                """,
                [
                    today,
                    row["impact_uuid"],
                    row["title"],
                    row["impact_pct"],
                    row["impact_style"],
                    row["tag_style"],
                    row["yes_count"],
                    row["no_count"],
                ],
            )

        for offset in range(days):
            day = today - timedelta(days=offset)
            stress = await _attempt(f"stress:{day}", sync_stress(day))
            if stress is None:
                continue
            samples = stress.pop("samples", [])
            for stamp, value, level in samples:
                conn.execute(
                    """
                    INSERT INTO whoop_stress_timeline (date, sampled_at, value, level)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (date, sampled_at) DO UPDATE SET
                        value = EXCLUDED.value,
                        level = EXCLUDED.level
                    """,
                    [day, stamp, value, level],
                )
            timeline_rows += len(samples)
            if samples or stress.get("stress_score") is not None:
                stress_days += 1

            # Sleep need / baseline are current-state, so only today's row gets
            # them; older rows carry stress only rather than a value copied
            # forward from a different day.
            daily = dict(stress)
            if offset == 0:
                daily.update(need)
                daily["sleeping_hr_baseline"] = baseline
            _upsert_daily(conn, day, daily)

    result = {
        "stress_days": stress_days,
        "stress_samples": timeline_rows,
        "hr_zones": len(zones),
        "behavior_impacts": len(impacts),
        "sleep_need": bool(need),
        "sleeping_hr_baseline": baseline,
        "failed": failures,
    }
    log.info("WHOOP private metrics sync complete: %s", result)
    return result


_DAILY_COLUMNS = (
    "need_total_min",
    "need_baseline_min",
    "need_strain_min",
    "need_debt_min",
    "need_nap_min",
    "optimal_bedtime_start",
    "optimal_bedtime_end",
    "recommended_tib_min",
    "stress_score",
    "stress_level",
    "stress_state",
    "stress_high_pct",
    "sleeping_hr_baseline",
)


def _upsert_daily(conn: Any, day: _date, values: dict) -> None:
    """Upsert one whoop_private_daily row.

    Every column appears in the DO UPDATE SET: a partial update that omits a
    column freezes whatever was written first, which is exactly how the WHOOP
    sleep/workout rows went stale in the past.
    """
    row = [values.get(column) for column in _DAILY_COLUMNS]
    assignments = ",\n                    ".join(
        f"{column} = EXCLUDED.{column}" for column in _DAILY_COLUMNS
    )
    placeholders = ", ".join("?" for _ in _DAILY_COLUMNS)
    conn.execute(
        f"""
        INSERT INTO whoop_private_daily (date, {", ".join(_DAILY_COLUMNS)}, content_hash)
        VALUES (?, {placeholders}, ?)
        ON CONFLICT (date) DO UPDATE SET
                    {assignments},
                    content_hash = EXCLUDED.content_hash
        WHERE EXCLUDED.content_hash != whoop_private_daily.content_hash
        """,
        [day, *row, _hash(*row)],
    )
