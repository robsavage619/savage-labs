from __future__ import annotations

import csv
import hashlib
import logging
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_COLUMNS = (
    "Cycle start time",
    "Cycle end time",
    "Cycle timezone",
    "Question text",
    "Answered yes",
    "Notes",
)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _parse_tz(offset: str) -> timezone | None:
    """Parse a WHOOP CSV `Cycle timezone` value ("UTC-08:00") into a tzinfo.

    The CSV spells the offset with a `UTC` prefix, unlike the API's
    `timezone_offset` ("-08:00") — hence a local parser rather than the one in
    `ingest.whoop`.
    """
    raw = offset.strip().removeprefix("UTC").strip()
    if len(raw) < 6 or raw[0] not in "+-":
        return None
    try:
        hours, minutes = raw[1:].split(":")
        sign = 1 if raw[0] == "+" else -1
        return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
    except (ValueError, IndexError):
        return None


def _parse_local(ts: str, tz: timezone) -> datetime | None:
    """Parse a CSV timestamp, which is wall-clock local time in `tz` (not UTC).

    Verified against the `sleep` table: CSV cycle start 2025-02-14 22:10:45
    matches that night's `ts_in` to the second in America/Los_Angeles.
    """
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None


def ingest_whoop_journal(csv_path: Path | None = None) -> dict:
    """Parse a WHOOP export `journal_entries.csv` and upsert into whoop_journal.

    Each row is one question answered for one WHOOP cycle. Rows are keyed on
    (cycle start, question), so re-running against a newer export is additive
    and idempotent.

    The row's `date` is taken from the cycle END, because that is the morning
    WHOOP scores the cycle and therefore the date `recovery` carries — keying
    on cycle start would misalign the join by a day for every entry.
    """
    from shc.config import settings
    from shc.db.schema import get_read_conn

    if csv_path is None:
        csv_path = settings.whoop_journal_csv_path

    if not csv_path.exists():
        raise FileNotFoundError(f"WHOOP journal CSV not found at {csv_path}")

    log.info("Parsing WHOOP journal CSV: %s", csv_path)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"WHOOP journal CSV missing expected columns {missing} — "
                f"schema drift? got={reader.fieldnames}"
            )
        rows = list(reader)

    conn = get_read_conn()
    inserted = 0
    updated = 0
    skipped: list[str] = []

    try:
        for i, row in enumerate(rows, start=2):  # 2 = first data line in the file
            tz = _parse_tz(row["Cycle timezone"])
            if tz is None:
                skipped.append(f"line {i}: unparseable timezone {row['Cycle timezone']!r}")
                continue

            start = _parse_local(row["Cycle start time"], tz)
            end = _parse_local(row["Cycle end time"], tz) if row["Cycle end time"].strip() else None
            if start is None:
                skipped.append(f"line {i}: unparseable cycle start {row['Cycle start time']!r}")
                continue

            # Trailing whitespace is real in this export ("Have any caffeine? "),
            # and would split one question into two GROUP BY buckets downstream.
            question = row["Question text"].strip()
            if not question:
                skipped.append(f"line {i}: empty question text")
                continue

            answered = row["Answered yes"].strip().lower()
            if answered not in ("true", "false"):
                skipped.append(f"line {i}: non-boolean 'Answered yes' {row['Answered yes']!r}")
                continue

            date = (end or start).date()
            notes = row["Notes"].strip() or None
            entry_id = _content_hash(start.isoformat(), question)
            row_hash = _content_hash(
                start.isoformat(),
                end.isoformat() if end else "",
                date.isoformat(),
                question,
                answered,
                notes or "",
            )

            before = conn.execute(
                "SELECT content_hash FROM whoop_journal WHERE id = ?", [entry_id]
            ).fetchone()
            conn.execute(
                """
                INSERT INTO whoop_journal
                    (id, cycle_start, cycle_end, date, question, answered_yes, notes, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    cycle_start  = EXCLUDED.cycle_start,
                    cycle_end    = EXCLUDED.cycle_end,
                    date         = EXCLUDED.date,
                    question     = EXCLUDED.question,
                    answered_yes = EXCLUDED.answered_yes,
                    notes        = EXCLUDED.notes,
                    content_hash = EXCLUDED.content_hash
                WHERE EXCLUDED.content_hash != whoop_journal.content_hash
                """,
                [entry_id, start, end, date, question, answered == "true", notes, row_hash],
            )
            if before is None:
                inserted += 1
            elif before[0] != row_hash:
                updated += 1
    finally:
        conn.close()

    for warning in skipped:
        log.warning("WHOOP journal ingest skipped %s", warning)

    result = {
        "rows": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": len(skipped),
        "skipped_detail": skipped,
    }
    log.info(
        "WHOOP journal ingest complete: %s",
        {k: v for k, v in result.items() if k != "skipped_detail"},
    )
    return result


# --- Private-API path -------------------------------------------------------
#
# The CSV export above is a point-in-time file Rob downloads by hand; its
# coverage stops dead at 2025-02-15. The functions below pull the same journal
# from WHOOP's private iOS API so the post-2025-03 window (the one that overlaps
# the REM drop) can actually be populated. Same table, `source` distinguishes.

_CATALOG_PATH = "/journal-service/v2/journals/behaviors"
_DRAFT_PATH = "/journal-service/v3/journals/drafts/mobile/{date}"

_CATALOG_ID_KEYS = ("behavior_tracker_id", "id", "tracker_id")
# `question_text` FIRST: catalog records carry both, and `title` is the bare
# noun ("Accutane") while `question_text` is the prose the CSV history stored
# ("Took Accutane?"). Preferring title would name the same behavior two ways.
_CATALOG_NAME_KEYS = ("question_text", "question", "name", "display_name", "label", "title")


def _first_key(record: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if record.get(key) not in (None, ""):
            return record[key]
    return None


async def _behavior_catalog() -> dict[int, str]:
    """Fetch the behavior catalog and return {behavior_tracker_id: question text}.

    The drafts endpoint returns tracker IDs, not prose — without this map every
    row's `question` would be an opaque integer and would not group with the
    CSV-sourced history in the correlations query.
    """
    from shc.ingest.whoop_private import WHOOPPrivateSchemaError, get

    catalog: dict[int, str] = {}
    next_token: str | None = None

    while True:
        params = {"next_token": next_token} if next_token else None
        payload = await get(_CATALOG_PATH, params=params)
        records = payload.get("records")
        if records is None:
            raise WHOOPPrivateSchemaError(
                f"behavior catalog response had no `records` key (got {sorted(payload)}) — "
                "journal-service shape changed, investigate before trusting a sync"
            )
        for record in records:
            raw_id = _first_key(record, _CATALOG_ID_KEYS)
            name = _first_key(record, _CATALOG_NAME_KEYS)
            if raw_id is None or name is None:
                continue
            try:
                catalog[int(raw_id)] = str(name).strip()
            except (TypeError, ValueError):
                continue

        next_token = payload.get("next_token")
        if not next_token:
            break

    if not catalog:
        raise WHOOPPrivateSchemaError(
            "behavior catalog parsed to zero entries — the id/name keys moved; "
            f"tried ids={_CATALOG_ID_KEYS} names={_CATALOG_NAME_KEYS}"
        )
    log.info("WHOOP behavior catalog: %d behaviors", len(catalog))
    return catalog


def _tracked_behaviors(payload: dict) -> list[dict]:
    """Pull the tracked-behaviors array out of a v3 drafts response."""
    journal = payload.get("journal")
    if not isinstance(journal, dict):
        return []
    behaviors = journal.get("tracked_behaviors")
    return behaviors if isinstance(behaviors, list) else []


async def sync_journal_api(days: int = 30) -> dict:
    """Pull the WHOOP journal from the private iOS API into whoop_journal.

    Walks back `days` calendar days, reading each date's auto-saved draft (the
    authoritative record of what was logged that day) and upserting one row per
    answered behavior.

    Note the date shift: the API serves a journal under its cycle START date,
    while this table keys on the cycle END (the morning WHOOP scores it), so a
    draft fetched at D is stored at D+1 to match the CSV path and the join
    against sleep/recovery.

    Rows are keyed on (date, question) within the `api` source namespace, so
    re-running is idempotent. Any date the CSV export already covers is skipped
    WHOLESALE — WHOOP reworded the questions between the export and the current
    API, so a per-question dedup silently fails to match and splits one
    behavior's history into two series in the correlations query. Skipped dates
    are reported under `collisions`, never dropped silently.
    """

    from shc.db.schema import write_ctx
    from shc.ingest.whoop_private import get

    catalog = await _behavior_catalog()
    today = datetime.now(UTC).date()
    dates = [today - timedelta(days=offset) for offset in range(days)]

    inserted = 0
    updated = 0
    collisions: list[str] = []
    unknown_ids: set[int] = set()
    failed_dates: list[str] = []
    entries_seen = 0
    unparseable = 0
    unanswered = 0

    async with write_ctx() as conn:
        for day in dates:
            # The API serves a journal under its cycle START date; this table's
            # `date` is the cycle END — the morning WHOOP scores the cycle, and
            # the date `recovery` carries. Verified against live data: the 13
            # entries the CSV files under 2025-02-15 are served by the API at
            # 2025-02-14. Dropping this shifts every row one day earlier and
            # mis-joins the entire table against sleep/recovery.
            entry_date = day + timedelta(days=1)

            # Skip whole dates the CSV export already covers, rather than
            # deduping question-by-question: WHOOP REWORDED the questions
            # between the export and the current API ("Have any caffeine?" →
            # "Consumed caffeine?", "Share your bed?" → "Shared your bed?"), so
            # a text match silently fails to collide and inserts a second copy
            # of a behavior already stored. The correlations query groups on
            # question alone, so that would split one behavior's history into
            # two half-length series. The CSV is a complete export for the days
            # it covers, so per-date is the right granularity.
            csv_rows = conn.execute(
                "SELECT COUNT(*) FROM whoop_journal WHERE date = ? AND source = 'csv'",
                [entry_date],
            ).fetchone()[0]
            if csv_rows:
                collisions.append(
                    f"{entry_date.isoformat()} — {csv_rows} CSV rows already cover this date"
                )
                continue

            try:
                payload = await get(_DRAFT_PATH.format(date=day.isoformat()))
            except Exception as exc:  # isolate per date — one gap shouldn't kill the backfill
                log.warning("WHOOP journal draft fetch failed for %s: %s", day, exc)
                failed_dates.append(day.isoformat())
                continue

            for behavior in _tracked_behaviors(payload):
                # The READ shape nests two sub-objects; it is NOT the flat
                # `tracker_inputs` shape the write path documents. Reading the
                # top level directly finds nothing and skips every entry.
                tracker = behavior.get("behavior_tracker") or {}
                answer = behavior.get("tracker_input") or {}

                raw_id = answer.get("behavior_tracker_id", tracker.get("id"))
                if raw_id is None:
                    unparseable += 1
                    continue
                try:
                    tracker_id = int(raw_id)
                except (TypeError, ValueError):
                    unparseable += 1
                    continue

                # `question_text` rides along on the entry, so the catalog is
                # only a fallback for a behavior that omits it.
                question = (tracker.get("question_text") or "").strip() or catalog.get(tracker_id)
                if not question:
                    unknown_ids.add(tracker_id)
                    continue

                # Three distinct states, and collapsing them loses real meaning:
                #   key absent      → a "bare" log; the behavior happened, no
                #                     yes/no was ever asked → True
                #   key present, None → the question was shown and NOT answered
                #                     → carries no information, must not be
                #                     recorded as "no" (that would invent a
                #                     negative observation the user never made)
                #   key present, bool → the real answer
                if "answered_yes" not in answer:
                    answered = True
                elif answer["answered_yes"] is None:
                    unanswered += 1
                    continue
                else:
                    answered = bool(answer["answered_yes"])

                entries_seen += 1
                magnitude_value = answer.get("magnitude_input_value")
                magnitude_label = answer.get("magnitude_input_label")
                notes = (payload.get("journal") or {}).get("notes") or None

                entry_id = _content_hash("api", entry_date.isoformat(), question)
                row_hash = _content_hash(
                    entry_date.isoformat(),
                    question,
                    str(answered),
                    str(magnitude_value),
                    str(magnitude_label),
                    notes or "",
                )

                before = conn.execute(
                    "SELECT content_hash FROM whoop_journal WHERE id = ?", [entry_id]
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO whoop_journal
                        (id, cycle_start, cycle_end, date, question, answered_yes, notes,
                         content_hash, source, behavior_tracker_id, magnitude_value,
                         magnitude_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'api', ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        cycle_start         = EXCLUDED.cycle_start,
                        cycle_end           = EXCLUDED.cycle_end,
                        date                = EXCLUDED.date,
                        question            = EXCLUDED.question,
                        answered_yes        = EXCLUDED.answered_yes,
                        notes               = EXCLUDED.notes,
                        content_hash        = EXCLUDED.content_hash,
                        source              = EXCLUDED.source,
                        behavior_tracker_id = EXCLUDED.behavior_tracker_id,
                        magnitude_value     = EXCLUDED.magnitude_value,
                        magnitude_label     = EXCLUDED.magnitude_label
                    WHERE EXCLUDED.content_hash != whoop_journal.content_hash
                    """,
                    [
                        entry_id,
                        datetime.combine(day, datetime.min.time(), tzinfo=UTC),
                        datetime.combine(entry_date, datetime.min.time(), tzinfo=UTC),
                        entry_date,
                        question,
                        answered,
                        notes,
                        row_hash,
                        tracker_id,
                        magnitude_value,
                        magnitude_label,
                    ],
                )
                if before is None:
                    inserted += 1
                elif before[0] != row_hash:
                    updated += 1

    if unanswered:
        log.info("WHOOP journal: %d questions were shown but never answered (skipped)", unanswered)
    if unparseable:
        log.warning(
            "WHOOP journal: %d entries carried no resolvable tracker id (skipped)", unparseable
        )
    if unknown_ids:
        log.warning(
            "WHOOP journal: %d tracker IDs absent from the catalog (skipped): %s",
            len(unknown_ids),
            sorted(unknown_ids)[:20],
        )
    for collision in collisions:
        log.warning("WHOOP journal collision — %s", collision)
    if failed_dates:
        log.warning("WHOOP journal: %d dates failed to fetch", len(failed_dates))

    result = {
        "days_requested": days,
        "entries_seen": entries_seen,
        "inserted": inserted,
        "updated": updated,
        "unparseable": unparseable,
        "unanswered": unanswered,
        "collisions": len(collisions),
        "collision_detail": collisions,
        "unknown_tracker_ids": sorted(unknown_ids),
        "failed_dates": failed_dates,
    }
    log.info(
        "WHOOP private journal sync complete: %s",
        {k: v for k, v in result.items() if k not in ("collision_detail", "unknown_tracker_ids")},
    )
    return result
