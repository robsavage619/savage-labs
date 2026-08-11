from __future__ import annotations

import csv
import hashlib
import logging
from datetime import datetime, timedelta, timezone
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
