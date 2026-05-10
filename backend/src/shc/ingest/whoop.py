from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import httpx

from shc.auth.keychain import load_token, store_token
from shc.config import settings
from shc.db.schema import write_ctx


class WHOOPAuthError(RuntimeError):
    """Raised when WHOOP tokens are invalid/expired and re-authorization is required."""


class WHOOPSchemaError(RuntimeError):
    """Raised when a WHOOP response is missing fields we expect — fails loud, never silent."""


def _client_id() -> str:
    return load_token("whoop", "client_id") or settings.whoop_client_id or ""


def _client_secret() -> str:
    return load_token("whoop", "client_secret") or settings.whoop_client_secret or ""

log = logging.getLogger(__name__)
_refresh_lock = asyncio.Lock()

WHOOP_BASE = "https://api.prod.whoop.com/developer"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"  # noqa: S105
SCOPES = (
    "offline read:recovery read:sleep read:workout read:cycles "
    "read:body_measurement read:profile"
)

_oauth_state: dict[str, str] = {}


def get_auth_url() -> str:
    state = secrets.token_urlsafe(16)
    _oauth_state["pending"] = state
    params = {
        "client_id": _client_id(),
        "redirect_uri": settings.whoop_redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


async def exchange_code(code: str, state: str) -> None:
    if state != _oauth_state.get("pending"):
        raise ValueError("OAuth state mismatch")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.whoop_redirect_uri,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
            },
        )
        resp.raise_for_status()
    tokens = resp.json()
    store_token("whoop", "access_token", tokens["access_token"])
    store_token("whoop", "refresh_token", tokens["refresh_token"])
    log.info("WHOOP tokens stored")


async def _refresh() -> str:
    """Refresh the access token. Serialised via _refresh_lock to prevent rotating-token races."""
    async with _refresh_lock:
        refresh = load_token("whoop", "refresh_token")
        if not refresh:
            raise WHOOPAuthError("No WHOOP refresh token — run OAuth flow first")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                },
            )
        if resp.status_code in (400, 401):
            raise WHOOPAuthError(f"WHOOP refresh rejected ({resp.status_code}) — re-authorization required")
        resp.raise_for_status()
        tokens = resp.json()
        store_token("whoop", "access_token", tokens["access_token"])
        store_token("whoop", "refresh_token", tokens["refresh_token"])
        log.info("WHOOP tokens refreshed")
        return tokens["access_token"]


async def _get(path: str, params: dict | None = None) -> dict:
    """GET with automatic 401 → re-auth and 429 → exponential backoff up to 3 retries."""
    token = load_token("whoop", "access_token")
    if not token:
        token = await _refresh()

    delay = 1.0
    last_resp: httpx.Response | None = None
    for attempt in range(4):
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{WHOOP_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        last_resp = resp
        if resp.status_code == 401:
            token = await _refresh()
            continue
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", delay))
            log.warning("WHOOP 429 on %s — backing off %.1fs (attempt %d/4)", path, retry_after, attempt + 1)
            await asyncio.sleep(retry_after)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()

    # Exhausted retries — raise the last response error.
    assert last_resp is not None
    last_resp.raise_for_status()
    raise RuntimeError(f"WHOOP _get exhausted retries on {path}")


_HASH_SCHEMA_VERSION = "v3"  # bump when ingestion adds/changes parsed fields


def _hash(data: dict) -> str:
    payload = _HASH_SCHEMA_VERSION + str(sorted(data.items()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _ms_to_min(ms: int | None) -> float | None:
    """Convert a WHOOP `*_milli` field to minutes (rounded)."""
    return round(ms / 60_000, 1) if ms else None


def _require(record: dict, *keys: str, kind: str) -> None:
    """Raise WHOOPSchemaError if any required key is missing — fails loud."""
    missing = [k for k in keys if k not in record]
    if missing:
        raise WHOOPSchemaError(
            f"WHOOP {kind} record missing required fields {missing} — schema drift? "
            f"record_keys={list(record.keys())}"
        )


async def _paginate(path: str) -> list[dict]:
    """Fetch all pages from a v2 WHOOP endpoint using next_token pagination."""
    records: list[dict] = []
    params: dict = {"limit": 25}
    while True:
        page = await _get(path, params)
        records.extend(page.get("records", []))
        next_token = page.get("next_token")
        if not next_token:
            break
        params = {"limit": 25, "nextToken": next_token}
    return records


# ── Recovery ─────────────────────────────────────────────────────────────────

async def sync_recovery() -> int:
    """Fetch recent recovery records and upsert into DuckDB."""
    records = await _paginate("/v2/recovery")
    skipped_no_score = 0
    async with write_ctx() as conn:
        for r in records:
            _require(r, "cycle_id", "score", kind="recovery")
            score = r.get("score") or {}
            if not score:
                # Recovery score may be empty for the most recent cycle if WHOOP
                # has not finished computing it. Surface as a counter — not silent.
                skipped_no_score += 1
                continue
            external_id = str(r["cycle_id"])
            rec_date = r.get("created_at", "")[:10]
            row = {
                "id": external_id,
                "source": "whoop",
                "date": rec_date,
                "score": score.get("recovery_score"),
                "hrv": score.get("hrv_rmssd_milli"),
                "rhr": score.get("resting_heart_rate"),
                "skin_temp": score.get("skin_temp_celsius"),
                "spo2": score.get("spo2_percentage"),
                "user_calibrating": score.get("user_calibrating"),
                "sleep_id": str(r["sleep_id"]) if r.get("sleep_id") else None,
                "content_hash": _hash(r),
            }
            conn.execute(
                """
                INSERT INTO recovery (id, source, date, score, hrv, rhr, skin_temp, spo2,
                                      user_calibrating, sleep_id, content_hash)
                VALUES ($id, $source, $date, $score, $hrv, $rhr, $skin_temp, $spo2,
                        $user_calibrating, $sleep_id, $content_hash)
                ON CONFLICT (id) DO UPDATE SET
                    score = EXCLUDED.score, hrv = EXCLUDED.hrv, rhr = EXCLUDED.rhr,
                    skin_temp = EXCLUDED.skin_temp, spo2 = EXCLUDED.spo2,
                    user_calibrating = EXCLUDED.user_calibrating,
                    sleep_id = EXCLUDED.sleep_id,
                    content_hash = EXCLUDED.content_hash
                WHERE EXCLUDED.content_hash != recovery.content_hash
                """,
                row,
            )
    if skipped_no_score:
        log.warning("WHOOP recovery: %d records skipped (no score yet)", skipped_no_score)
    log.info("synced %d WHOOP recovery records", len(records) - skipped_no_score)
    return len(records) - skipped_no_score


# ── Sleep ────────────────────────────────────────────────────────────────────

async def sync_sleep() -> int:
    records = await _paginate("/v2/activity/sleep")
    skipped_no_score = 0
    async with write_ctx() as conn:
        for r in records:
            _require(r, "id", "start", "end", "score", kind="sleep")
            score = r.get("score") or {}
            if not score:
                skipped_no_score += 1
                continue
            ss = score.get("stage_summary") or {}
            needed = score.get("sleep_needed") or {}
            external_id = str(r["id"])

            need_baseline = _ms_to_min(needed.get("baseline_milli"))
            need_debt = _ms_to_min(needed.get("need_from_sleep_debt_milli"))
            need_strain = _ms_to_min(needed.get("need_from_recent_strain_milli"))
            need_nap = _ms_to_min(needed.get("need_from_recent_nap_milli"))
            # Total need = baseline + debt + strain - nap_credit (nap reduces need).
            total_need = None
            parts = [need_baseline, need_debt, need_strain]
            if any(p is not None for p in parts):
                total_need = round(sum(p or 0 for p in parts) - (need_nap or 0), 1)

            row = {
                "id": external_id,
                "source": "whoop",
                "night_date": r.get("start", "")[:10],
                "ts_in": r.get("start"),
                "ts_out": r.get("end"),
                "stages_json": str(ss),
                # Sleep endpoint does NOT return spo2_percentage — that's on
                # the recovery endpoint. Leave NULL here; it's joined later.
                "spo2_avg": None,
                "respiratory_rate": score.get("respiratory_rate"),
                "hrv": None,  # HRV is on recovery, not sleep
                "is_nap": bool(r.get("nap")),
                "sleep_performance_pct": score.get("sleep_performance_percentage"),
                "sleep_efficiency_pct": score.get("sleep_efficiency_percentage"),
                "sleep_consistency_pct": score.get("sleep_consistency_percentage"),
                "disturbance_count": ss.get("disturbance_count"),
                "sleep_cycle_count": ss.get("sleep_cycle_count"),
                "sleep_needed_min": total_need,
                "sleep_need_baseline_min": need_baseline,
                "sleep_need_debt_min": need_debt,
                "sleep_need_strain_min": need_strain,
                "sleep_need_nap_min": need_nap,
                "sws_min": _ms_to_min(ss.get("total_slow_wave_sleep_time_milli")),
                "rem_min": _ms_to_min(ss.get("total_rem_sleep_time_milli")),
                "light_min": _ms_to_min(ss.get("total_light_sleep_time_milli")),
                "awake_min": _ms_to_min(ss.get("total_awake_time_milli")),
                "in_bed_min": _ms_to_min(ss.get("total_in_bed_time_milli")),
                "no_data_min": _ms_to_min(ss.get("total_no_data_time_milli")),
                "content_hash": _hash(r),
            }
            conn.execute(
                """
                INSERT INTO sleep (id, source, night_date, ts_in, ts_out, stages_json,
                                   spo2_avg, respiratory_rate, hrv,
                                   is_nap, sleep_performance_pct, sleep_efficiency_pct,
                                   sleep_consistency_pct, disturbance_count, sleep_cycle_count,
                                   sleep_needed_min, sleep_need_baseline_min,
                                   sleep_need_debt_min, sleep_need_strain_min, sleep_need_nap_min,
                                   sws_min, rem_min, light_min, awake_min,
                                   in_bed_min, no_data_min,
                                   content_hash)
                VALUES ($id, $source, $night_date, $ts_in, $ts_out, $stages_json,
                        $spo2_avg, $respiratory_rate, $hrv,
                        $is_nap, $sleep_performance_pct, $sleep_efficiency_pct,
                        $sleep_consistency_pct, $disturbance_count, $sleep_cycle_count,
                        $sleep_needed_min, $sleep_need_baseline_min,
                        $sleep_need_debt_min, $sleep_need_strain_min, $sleep_need_nap_min,
                        $sws_min, $rem_min, $light_min, $awake_min,
                        $in_bed_min, $no_data_min,
                        $content_hash)
                ON CONFLICT (id) DO UPDATE SET
                    stages_json = EXCLUDED.stages_json,
                    respiratory_rate = EXCLUDED.respiratory_rate,
                    is_nap = EXCLUDED.is_nap,
                    sleep_performance_pct = EXCLUDED.sleep_performance_pct,
                    sleep_efficiency_pct = EXCLUDED.sleep_efficiency_pct,
                    sleep_consistency_pct = EXCLUDED.sleep_consistency_pct,
                    disturbance_count = EXCLUDED.disturbance_count,
                    sleep_cycle_count = EXCLUDED.sleep_cycle_count,
                    sleep_needed_min = EXCLUDED.sleep_needed_min,
                    sleep_need_baseline_min = EXCLUDED.sleep_need_baseline_min,
                    sleep_need_debt_min = EXCLUDED.sleep_need_debt_min,
                    sleep_need_strain_min = EXCLUDED.sleep_need_strain_min,
                    sleep_need_nap_min = EXCLUDED.sleep_need_nap_min,
                    sws_min = EXCLUDED.sws_min,
                    rem_min = EXCLUDED.rem_min,
                    light_min = EXCLUDED.light_min,
                    awake_min = EXCLUDED.awake_min,
                    in_bed_min = EXCLUDED.in_bed_min,
                    no_data_min = EXCLUDED.no_data_min,
                    content_hash = EXCLUDED.content_hash
                WHERE EXCLUDED.content_hash != sleep.content_hash
                """,
                row,
            )
    if skipped_no_score:
        log.warning("WHOOP sleep: %d records skipped (no score yet)", skipped_no_score)
    log.info("synced %d WHOOP sleep records", len(records) - skipped_no_score)
    return len(records) - skipped_no_score


# Strength modalities already tracked by Hevy — skip mirroring to cardio_sessions.
_STRENGTH_KINDS: frozenset[str] = frozenset({"powerlifting", "weightlifting"})

_SPORT_NAMES: dict[int, str] = {
    -1: "activity",
    0: "running",
    1: "cycling",
    16: "baseball",
    17: "basketball",
    18: "rowing",
    19: "fencing",
    20: "field hockey",
    21: "football",
    22: "golf",
    24: "ice hockey",
    25: "lacrosse",
    27: "martial arts",
    28: "mountain biking",
    29: "obstacle course racing",
    30: "powerlifting",
    31: "rock climbing",
    32: "rowing",
    33: "rugby",
    34: "skiing",
    35: "snowboarding",
    36: "soccer",
    37: "softball",
    38: "squash",
    39: "swimming",
    40: "tennis",
    41: "track & field",
    42: "volleyball",
    43: "water polo",
    44: "wrestling",
    45: "yoga",
    47: "weightlifting",
    48: "cross country skiing",
    49: "functional fitness",
    50: "duathlon",
    51: "gymnastics",
    52: "hiking/rucking",
    53: "horseback riding",
    55: "triathlon",
    56: "walking",
    57: "surfing",
    58: "elliptical",
    59: "stairmaster",
    63: "meditation",
    64: "other",
    65: "pickleball",
    66: "padel",
    67: "boxing",
    68: "dance",
    69: "pilates",
    70: "kickboxing",
    71: "pickleball",
    101: "pickleball",
    126: "pickleball",
}


def _duration_min(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(1, round((t1 - t0).total_seconds() / 60))
    except ValueError:
        return None


# ── Workouts ─────────────────────────────────────────────────────────────────

async def sync_workout() -> int:
    """Fetch WHOOP workout activities and upsert into the workouts and cardio_sessions tables."""
    records = await _paginate("/v2/activity/workout")
    skipped_no_score = 0
    async with write_ctx() as conn:
        for r in records:
            _require(r, "id", "start", "score", kind="workout")
            score = r.get("score") or {}
            if not score:
                skipped_no_score += 1
                continue
            sport_id = r.get("sport_id", -1)
            kind = _SPORT_NAMES.get(sport_id, f"sport_{sport_id}")
            kcal_kj = score.get("kilojoule")
            kcal = round(kcal_kj / 4.184, 1) if kcal_kj else None
            zones = score.get("zone_durations") or {}
            wid = f"whoop_w_{r['id']}"
            chash = _hash(r)
            row = {
                "id": wid,
                "source": "whoop",
                "started_at": r.get("start"),
                "ended_at": r.get("end"),
                "kind": kind,
                "sport_id": sport_id,
                "sport_name": kind,
                "strain": score.get("strain"),
                "avg_hr": score.get("average_heart_rate"),
                "max_hr": score.get("max_heart_rate"),
                "kcal": kcal,
                "percent_recorded": score.get("percent_recorded"),
                "distance_meter": score.get("distance_meter"),
                "altitude_gain_meter": score.get("altitude_gain_meter"),
                "altitude_change_meter": score.get("altitude_change_meter"),
                "zone_zero_min": _ms_to_min(zones.get("zone_zero_milli")),
                "zone_one_min": _ms_to_min(zones.get("zone_one_milli")),
                "zone_two_min": _ms_to_min(zones.get("zone_two_milli")),
                "zone_three_min": _ms_to_min(zones.get("zone_three_milli")),
                "zone_four_min": _ms_to_min(zones.get("zone_four_milli")),
                "zone_five_min": _ms_to_min(zones.get("zone_five_milli")),
                "notes": None,
                "content_hash": chash,
            }
            conn.execute(
                """
                INSERT INTO workouts (id, source, started_at, ended_at, kind, sport_id, sport_name,
                                      strain, avg_hr, max_hr, kcal,
                                      percent_recorded, distance_meter,
                                      altitude_gain_meter, altitude_change_meter,
                                      zone_zero_min, zone_one_min, zone_two_min,
                                      zone_three_min, zone_four_min, zone_five_min,
                                      notes, content_hash)
                VALUES ($id, $source, $started_at, $ended_at, $kind, $sport_id, $sport_name,
                        $strain, $avg_hr, $max_hr, $kcal,
                        $percent_recorded, $distance_meter,
                        $altitude_gain_meter, $altitude_change_meter,
                        $zone_zero_min, $zone_one_min, $zone_two_min,
                        $zone_three_min, $zone_four_min, $zone_five_min,
                        $notes, $content_hash)
                ON CONFLICT (id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    sport_id = EXCLUDED.sport_id,
                    sport_name = EXCLUDED.sport_name,
                    strain = EXCLUDED.strain,
                    avg_hr = EXCLUDED.avg_hr, max_hr = EXCLUDED.max_hr,
                    kcal = EXCLUDED.kcal,
                    percent_recorded = EXCLUDED.percent_recorded,
                    distance_meter = EXCLUDED.distance_meter,
                    altitude_gain_meter = EXCLUDED.altitude_gain_meter,
                    altitude_change_meter = EXCLUDED.altitude_change_meter,
                    zone_zero_min = EXCLUDED.zone_zero_min,
                    zone_one_min = EXCLUDED.zone_one_min,
                    zone_two_min = EXCLUDED.zone_two_min,
                    zone_three_min = EXCLUDED.zone_three_min,
                    zone_four_min = EXCLUDED.zone_four_min,
                    zone_five_min = EXCLUDED.zone_five_min,
                    content_hash = EXCLUDED.content_hash
                """,
                row,
            )
            # Mirror into cardio_sessions so cardio_age_days / cardio_min_28d stay fresh.
            # Skip pure strength modalities already tracked by Hevy.
            if kind not in _STRENGTH_KINDS:
                # Pre-compute a zone distribution JSON so cardio reports can render it.
                zone_dist = {
                    "z0": _ms_to_min(zones.get("zone_zero_milli")),
                    "z1": _ms_to_min(zones.get("zone_one_milli")),
                    "z2": _ms_to_min(zones.get("zone_two_milli")),
                    "z3": _ms_to_min(zones.get("zone_three_milli")),
                    "z4": _ms_to_min(zones.get("zone_four_milli")),
                    "z5": _ms_to_min(zones.get("zone_five_milli")),
                }
                conn.execute(
                    """
                    INSERT INTO cardio_sessions
                        (id, date, modality, duration_min, avg_hr, rpe,
                         zone_distribution_json, content_hash)
                    VALUES ($id, $date, $modality, $duration_min, $avg_hr,
                            NULL, $zones, $content_hash)
                    ON CONFLICT (id) DO UPDATE SET
                        modality    = EXCLUDED.modality,
                        duration_min = EXCLUDED.duration_min,
                        avg_hr      = EXCLUDED.avg_hr,
                        zone_distribution_json = EXCLUDED.zone_distribution_json,
                        content_hash = EXCLUDED.content_hash
                    WHERE EXCLUDED.content_hash != cardio_sessions.content_hash
                    """,
                    {
                        "id": wid,
                        "date": (r.get("start") or "")[:10],
                        "modality": kind,
                        "duration_min": _duration_min(r.get("start"), r.get("end")),
                        "avg_hr": score.get("average_heart_rate"),
                        "zones": str(zone_dist) if any(v for v in zone_dist.values()) else None,
                        "content_hash": chash,
                    },
                )
    if skipped_no_score:
        log.warning("WHOOP workout: %d records skipped (no score yet)", skipped_no_score)
    log.info("synced %d WHOOP workout records", len(records) - skipped_no_score)
    return len(records) - skipped_no_score


# ── Cycle ────────────────────────────────────────────────────────────────────

async def sync_cycle() -> int:
    """Fetch daily cycle records (strain, kcal, avg/max HR) and upsert into daily_cycle."""
    records = await _paginate("/v2/cycle")
    skipped: dict[str, int] = {"unscorable": 0, "no_score": 0}
    async with write_ctx() as conn:
        for r in records:
            _require(r, "id", "start", kind="cycle")
            score = r.get("score") or {}
            score_state = r.get("score_state")
            if score_state == "UNSCORABLE":
                skipped["unscorable"] += 1
                continue
            if score_state not in ("SCORED", "PENDING_SCORE"):
                # Unknown state — log it but don't drop silently.
                log.warning("WHOOP cycle %s has unknown score_state=%s", r.get("id"), score_state)
                continue
            row = {
                "id": str(r["id"]),
                "date": r.get("start", "")[:10],
                "score_state": score_state,
                "strain": score.get("strain"),
                "kilojoule": score.get("kilojoule"),
                "avg_hr": score.get("average_heart_rate"),
                "max_hr": score.get("max_heart_rate"),
                "percent_recorded": score.get("percent_recorded"),
                "start_ts": r.get("start"),
                "end_ts": r.get("end"),
                "content_hash": _hash(r),
            }
            conn.execute(
                """
                INSERT INTO daily_cycle (id, date, score_state, strain, kilojoule,
                                         avg_hr, max_hr, percent_recorded,
                                         start_ts, end_ts, content_hash)
                VALUES ($id, $date, $score_state, $strain, $kilojoule,
                        $avg_hr, $max_hr, $percent_recorded,
                        $start_ts, $end_ts, $content_hash)
                ON CONFLICT (id) DO UPDATE SET
                    score_state = EXCLUDED.score_state,
                    strain = EXCLUDED.strain, kilojoule = EXCLUDED.kilojoule,
                    avg_hr = EXCLUDED.avg_hr, max_hr = EXCLUDED.max_hr,
                    percent_recorded = EXCLUDED.percent_recorded,
                    start_ts = EXCLUDED.start_ts, end_ts = EXCLUDED.end_ts,
                    content_hash = EXCLUDED.content_hash
                WHERE EXCLUDED.content_hash != daily_cycle.content_hash
                """,
                row,
            )
    if skipped["unscorable"]:
        log.warning("WHOOP cycle: %d records skipped (UNSCORABLE)", skipped["unscorable"])
    log.info("synced %d WHOOP cycle records", len(records) - sum(skipped.values()))
    return len(records) - sum(skipped.values())


# ── Body Measurement ─────────────────────────────────────────────────────────

async def sync_body_measurement() -> int:
    """Fetch height/weight/max-HR. Single row endpoint — no pagination."""
    data = await _get("/v2/user/measurement/body")
    _require(data, "height_meter", "weight_kilogram", "max_heart_rate", kind="body_measurement")
    measured_at = datetime.now(UTC).isoformat()
    row = {
        "source": "whoop",
        "measured_at": measured_at,
        "height_meter": data.get("height_meter"),
        "weight_kg": data.get("weight_kilogram"),
        "max_heart_rate": data.get("max_heart_rate"),
        "content_hash": _hash(data),
    }
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO body_measurement (source, measured_at, height_meter, weight_kg,
                                          max_heart_rate, content_hash)
            VALUES ($source, $measured_at, $height_meter, $weight_kg,
                    $max_heart_rate, $content_hash)
            ON CONFLICT (source, measured_at) DO UPDATE SET
                height_meter = EXCLUDED.height_meter,
                weight_kg = EXCLUDED.weight_kg,
                max_heart_rate = EXCLUDED.max_heart_rate,
                content_hash = EXCLUDED.content_hash
            WHERE EXCLUDED.content_hash != body_measurement.content_hash
            """,
            row,
        )
    log.info(
        "synced WHOOP body measurement: max_hr=%s height=%sm weight=%skg",
        data.get("max_heart_rate"), data.get("height_meter"), data.get("weight_kilogram"),
    )
    return 1


# ── User Profile ─────────────────────────────────────────────────────────────

async def sync_user_profile() -> int:
    """Fetch the WHOOP user profile (identity audit trail)."""
    data = await _get("/v2/user/profile/basic")
    _require(data, "user_id", kind="user_profile")
    row = {
        "user_id": data.get("user_id"),
        "email": data.get("email"),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "last_synced_at": datetime.now(UTC).isoformat(),
    }
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO whoop_user_profile (user_id, email, first_name, last_name, last_synced_at)
            VALUES ($user_id, $email, $first_name, $last_name, $last_synced_at)
            ON CONFLICT (user_id) DO UPDATE SET
                email = EXCLUDED.email,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                last_synced_at = EXCLUDED.last_synced_at
            """,
            row,
        )
    log.info("synced WHOOP user profile: user_id=%s", data.get("user_id"))
    return 1


# ── Orchestration ────────────────────────────────────────────────────────────

async def sync_all() -> dict[str, int]:
    """Full sync — called by APScheduler 2x/day.

    Only sets needs_reauth on WHOOPAuthError. Transient failures (429, network
    errors, schema drift) are logged but do not trigger the reauth banner.
    Per-endpoint failures are isolated so a single bad endpoint doesn't kill
    the whole sync.
    """
    results: dict[str, int] = {}
    endpoints: list[tuple[str, Any]] = [
        ("recovery", sync_recovery),
        ("sleep", sync_sleep),
        ("workout", sync_workout),
        ("cycle", sync_cycle),
        ("body_measurement", sync_body_measurement),
        ("user_profile", sync_user_profile),
    ]
    auth_failure: WHOOPAuthError | None = None
    other_failures: list[str] = []

    for name, fn in endpoints:
        try:
            results[name] = await fn()
        except WHOOPAuthError as e:
            auth_failure = e
            results[name] = -1
            break  # Auth dead — stop trying.
        except WHOOPSchemaError:
            log.exception("WHOOP %s schema drift — investigate", name)
            results[name] = -1
            other_failures.append(name)
        except Exception:
            log.exception("WHOOP %s sync failed (transient)", name)
            results[name] = -1
            other_failures.append(name)

    async with write_ctx() as conn:
        if auth_failure:
            conn.execute(
                "INSERT INTO oauth_state (source, needs_reauth) VALUES ('whoop', TRUE) "
                "ON CONFLICT (source) DO UPDATE SET needs_reauth = TRUE"
            )
        else:
            conn.execute(
                "INSERT INTO oauth_state (source, last_sync_at, needs_reauth) "
                "VALUES ('whoop', $ts, FALSE) ON CONFLICT (source) DO UPDATE "
                "SET last_sync_at = EXCLUDED.last_sync_at, needs_reauth = FALSE",
                {"ts": datetime.now(UTC).isoformat()},
            )

    if auth_failure:
        raise auth_failure
    if other_failures:
        # Surface partial-failure clearly — never silent.
        log.error("WHOOP sync completed with failures on: %s", other_failures)
    return results
