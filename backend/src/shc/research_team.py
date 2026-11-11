"""The research team's autonomy layer: specialist agendas, custom measurements
defined as guarded read-only SQL, a free exploration tier, and the notebook
entries that record all three.

Specialists act only through the Lab API. Nothing here writes beliefs or
touches the training engine: an agenda is a researcher's own plan, an
exploration is a notebook entry, and a custom measurement only reaches a
formal question once the methodologist approves it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import duckdb

from shc import research

log = logging.getLogger(__name__)

RESEARCHERS: dict[str, dict[str, str]] = {
    "hypertrophy": {
        "name": "Hypertrophy",
        "field": "Muscle growth",
        "curiosity": "Volume dose-response per muscle, the emphasis muscles, and what stalls progression.",
    },
    "recovery": {
        "name": "Recovery",
        "field": "Sleep and autonomic load",
        "curiosity": "Sleep architecture, HRV and resting heart rate as mediators, and early illness signals.",
    },
    "conditioning": {
        "name": "Conditioning",
        "field": "Aerobic base",
        "curiosity": "Aerobic base minutes, VO2 trend, resting heart rate, and how court time loads the week.",
    },
    "metabolic": {
        "name": "Metabolic",
        "field": "Body composition",
        "curiosity": "Recomposition: weight trend, steps, daylight, and intake when it is logged.",
    },
}

LEAD_STATUSES = ("open", "chasing", "parked", "closed")
CUSTOM_PREFIX = "custom:"
EXPLORE_ROW_CAP = 2000
FEATURE_ROW_CAP = 50_000
QUERY_TIMEOUT_S = 10.0
_MIN_FEATURE_ROWS = 10
_MAX_TEXT = 4000
_MAX_LEADS = 30
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{2,40}$")


class TeamError(ValueError):
    """A request the team layer refuses: bad shape, unknown researcher, wrong state."""


class SqlGuardError(TeamError):
    """SQL the read-only guard refuses or that failed under the guard."""


# ── Read-only SQL guard ─────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|ATTACH|DETACH|COPY|EXPORT|IMPORT|"
    r"PRAGMA|INSTALL|LOAD|SET|CALL|CHECKPOINT|VACUUM)\b",
    re.IGNORECASE,
)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
# Table functions are where file, network and catalog access hide (read_csv,
# glob, query, duckdb_settings, pragma_*), so only pure generators and the
# schema catalog (so researchers can find tables and columns) pass.
_ALLOWED_TABLE_FUNCTIONS = {
    "range",
    "generate_series",
    "unnest",
    "duckdb_tables",
    "duckdb_columns",
    "duckdb_views",
}
_DENIED_FUNCTIONS = {"getenv", "current_setting", "nextval", "currval", "setseed"}
_HIDDEN_TABLES = {"oauth_state", "schema_version"}


def _ast_names(
    node: Any, tables: list[tuple[str, str, str]], tfuncs: set[str], funcs: set[str], ctes: set[str]
) -> None:
    if isinstance(node, dict):
        kind = node.get("type")
        if kind == "BASE_TABLE":
            tables.append(
                (
                    str(node.get("catalog_name") or "").lower(),
                    str(node.get("schema_name") or "").lower(),
                    str(node.get("table_name") or "").lower(),
                )
            )
        elif kind == "TABLE_FUNCTION":
            tfuncs.add(str((node.get("function") or {}).get("function_name", "")).lower())
        if node.get("class") == "FUNCTION":
            funcs.add(str(node.get("function_name", "")).lower())
        for m in (node.get("cte_map") or {}).get("map", []) or []:
            ctes.add(str(m.get("key", "")).lower())
        for v in node.values():
            _ast_names(v, tables, tfuncs, funcs, ctes)
    elif isinstance(node, list):
        for v in node:
            _ast_names(v, tables, tfuncs, funcs, ctes)


def check_sql(conn: duckdb.DuckDBPyConnection, sql: str) -> None:
    """Refuse anything but one plain SELECT over the app's own tables.

    `get_read_conn()` is a cursor on the shared read-write connection, and
    DuckDB will not open the same file read-only in-process, so the guard is
    layered instead: keyword scan, parser statement type, an AST allowlist of
    tables and table functions, and (in `_execute`) a transaction that is
    always rolled back.

    Args:
        conn: Any connection to the database the SQL will run against.
        sql: The proposed query.

    Raises:
        SqlGuardError: If the SQL is not a single read-only SELECT over known tables.
    """
    text = (sql or "").strip()
    if not text:
        raise SqlGuardError("empty query")
    if not re.match(r"(?is)^(SELECT|WITH)\b", text):
        raise SqlGuardError("query must start with SELECT or WITH")
    hit = _FORBIDDEN.search(_STRING_LITERAL.sub("''", text))
    if hit:
        raise SqlGuardError(f"{hit.group(1).upper()} is not allowed; read-only SELECT only")
    try:
        statements = conn.extract_statements(text)
    except duckdb.Error as exc:
        raise SqlGuardError(f"could not parse: {exc}") from exc
    if len(statements) != 1:
        raise SqlGuardError("exactly one statement allowed")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise SqlGuardError("only SELECT statements are allowed")
    row = conn.execute("SELECT json_serialize_sql(?)", [text]).fetchone()
    ast = json.loads(row[0]) if row else {"error": True}
    if ast.get("error"):
        raise SqlGuardError(f"could not parse: {ast.get('error_message', 'unknown error')}")
    tables: list[tuple[str, str, str]] = []
    tfuncs: set[str] = set()
    funcs: set[str] = set()
    ctes: set[str] = set()
    _ast_names(ast, tables, tfuncs, funcs, ctes)
    bad_tf = tfuncs - _ALLOWED_TABLE_FUNCTIONS
    if bad_tf:
        raise SqlGuardError(f"table function(s) not allowed: {', '.join(sorted(bad_tf))}")
    bad_f = {f for f in funcs if f in _DENIED_FUNCTIONS or f.startswith("read_")}
    if bad_f:
        raise SqlGuardError(f"function(s) not allowed: {', '.join(sorted(bad_f))}")
    db = (conn.execute("SELECT current_database()").fetchone() or [""])[0].lower()
    known = {
        r[0].lower()
        for r in conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main' AND NOT internal "
            "UNION ALL SELECT view_name FROM duckdb_views() WHERE schema_name = 'main' AND NOT internal"
        ).fetchall()
    } - _HIDDEN_TABLES
    for catalog, schema, name in tables:
        if catalog not in ("", db) or schema not in ("", "main"):
            raise SqlGuardError(f"only the app's own tables are readable, not {name!r}")
        if name not in ctes and name not in known:
            raise SqlGuardError(f"unknown table {name!r}")


def _execute(
    conn: duckdb.DuckDBPyConnection, sql: str, cap: int, timeout_s: float
) -> tuple[list[str], list[tuple], bool]:
    """Guard, then run in a rolled-back transaction with a row cap and a timer interrupt."""
    check_sql(conn, sql)
    cur = conn.cursor()
    timer = threading.Timer(timeout_s, cur.interrupt)
    try:
        cur.execute("BEGIN TRANSACTION")
        timer.start()
        try:
            cur.execute(sql.strip())
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchmany(cap + 1)
        except duckdb.InterruptException as exc:
            raise SqlGuardError(f"query ran past {timeout_s:g}s and was stopped") from exc
        except duckdb.Error as exc:
            raise SqlGuardError(f"query failed: {exc}") from exc
        finally:
            timer.cancel()
            with contextlib.suppress(duckdb.Error):
                cur.execute("ROLLBACK")
    finally:
        cur.close()
    return cols, rows[:cap], len(rows) > cap


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if v is None or isinstance(v, bool | int | float | str):
        return v
    return str(v)


def run_query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    cap: int = EXPLORE_ROW_CAP,
    timeout_s: float = QUERY_TIMEOUT_S,
) -> dict:
    """Free exploration: guarded read-only SQL, capped rows.

    Args:
        conn: Read connection.
        sql: One SELECT/WITH statement.
        cap: Maximum rows returned (never above EXPLORE_ROW_CAP).
        timeout_s: Wall-clock limit before the query is interrupted.

    Returns:
        ``{"columns", "rows", "row_count", "truncated"}`` with JSON-safe cells.

    Raises:
        SqlGuardError: If the guard refuses the SQL or it fails.
    """
    cols, rows, truncated = _execute(conn, sql, min(cap, EXPLORE_ROW_CAP), timeout_s)
    out = [[_jsonable(v) for v in r] for r in rows]
    return {"columns": cols, "rows": out, "row_count": len(out), "truncated": truncated}


# ── Custom measurements ─────────────────────────────────────────────────────


def _as_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    raise TypeError(f"{v!r} is not a date")


def _series_from(conn: duckdb.DuckDBPyConnection, sql: str) -> dict[date, float]:
    cols, rows, truncated = _execute(conn, sql, FEATURE_ROW_CAP, QUERY_TIMEOUT_S)
    if len(cols) != 2:
        raise SqlGuardError(
            f"a measurement returns exactly two columns (date, value), got {len(cols)}"
        )
    if truncated:
        raise SqlGuardError(f"returns more than {FEATURE_ROW_CAP} rows; one row per date")
    out: dict[date, float] = {}
    for d, v in rows:
        if d is None or v is None:
            continue
        try:
            day = _as_date(d)
        except (TypeError, ValueError) as exc:
            raise SqlGuardError(f"first column must be a date, got {d!r}") from exc
        if isinstance(v, bool) or not isinstance(v, int | float | Decimal):
            raise SqlGuardError(f"second column must be numeric, got {v!r}")
        if day in out:
            raise SqlGuardError(f"more than one row for {day}; one row per date")
        out[day] = float(v)
    return out


def _custom_name(name: str) -> str:
    slug = name.removeprefix(CUSTOM_PREFIX)
    if not _SLUG.match(slug):
        raise TeamError("measurement slug must be 3-41 chars of a-z, 0-9 and _")
    return f"{CUSTOM_PREFIX}{slug}"


def _approved_sql(conn: duckdb.DuckDBPyConnection, name: str) -> str | None:
    row = conn.execute(
        "SELECT sql FROM research_custom_features WHERE name = ? AND status = 'approved'", [name]
    ).fetchone()
    return row[0] if row else None


def known_custom(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """True only for an approved custom measurement."""
    return _approved_sql(conn, name) is not None


def custom_series(conn: duckdb.DuckDBPyConnection, name: str) -> dict[date, float]:
    """An approved custom measurement as {date: value}.

    Raises:
        ValueError: If the measurement is unknown or not approved.
        SqlGuardError: If its SQL now fails the guard or shape check.
    """
    sql = _approved_sql(conn, name)
    if sql is None:
        raise ValueError(f"unknown or unapproved feature {name!r}")
    return _series_from(conn, sql)


# Default goal for a measurement, by the field of the specialist who proposed it.
OWNER_GOAL = {
    "hypertrophy": "muscle",
    "metabolic": "body",
    "conditioning": "cardio",
    "recovery": "recovery",
}


def custom_goal(conn: duckdb.DuckDBPyConnection, name: str) -> str | None:
    """The goal a custom measurement serves, as declared when it was proposed."""
    row = conn.execute(
        "SELECT goal FROM research_custom_features WHERE name = ?", [name]
    ).fetchone()
    return row[0] if row and row[0] else None


def propose_custom(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    owner: str,
    description: str,
    unit: str,
    timing: str,
    sql: str,
    goal: str | None = None,
) -> dict:
    """Validate a measurement by running it, then store it as `proposed`.

    Args:
        conn: Write connection.
        slug: Short name; stored as ``custom:<slug>``.
        owner: The proposing specialist.
        description: What the value measures, in plain words.
        unit: Unit of the value.
        timing: ``morning`` (read on waking) or ``day`` (accumulated over the day).
        sql: One SELECT returning (date, value), one row per date.
        goal: The goal it measures when used as an outcome (muscle, body, cardio,
            recovery); defaults to the owner's field. It sets the goal weight in
            the value score, so a strength measure proposed by the recovery
            specialist still counts as muscle.

    Returns:
        The stored row's name, status and validation summary.

    Raises:
        TeamError: On a bad field, a name already proposed or approved, or SQL
            that fails the guard, shape or minimum-rows check.
    """
    name = _custom_name(slug)
    if owner not in RESEARCHERS:
        raise TeamError(f"owner must be one of {', '.join(RESEARCHERS)}")
    if timing not in ("morning", "day"):
        raise TeamError("timing must be 'morning' or 'day'")
    if len(description.strip()) < 10 or not unit.strip():
        raise TeamError("description (10+ chars) and unit are required")
    goal = goal or OWNER_GOAL[owner]
    if goal not in research.GOAL_WEIGHTS:
        raise TeamError(f"goal must be one of {', '.join(research.GOAL_WEIGHTS)}")
    existing = conn.execute(
        "SELECT status FROM research_custom_features WHERE name = ?", [name]
    ).fetchone()
    if existing and existing[0] != "rejected":
        raise TeamError(f"{name} is already {existing[0]}; propose a new slug to change it")
    s = _series_from(conn, sql)
    if len(s) < _MIN_FEATURE_ROWS:
        raise SqlGuardError(
            f"returns {len(s)} usable rows; a measurement needs at least {_MIN_FEATURE_ROWS}"
        )
    if max(s) > date.today():
        raise SqlGuardError(
            f"has rows dated after today ({max(s)}); a measurement can't see the future"
        )
    conn.execute("DELETE FROM research_custom_features WHERE name = ?", [name])
    conn.execute(
        "INSERT INTO research_custom_features (name, owner, description, unit, timing, sql, goal) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [name, owner, description.strip(), unit.strip(), timing, sql.strip(), goal],
    )
    summary = {"days": len(s), "first": str(min(s)), "last": str(max(s))}
    research.note(
        conn,
        owner,
        "measurement",
        f"Proposed {name}",
        f"{description.strip()} ({unit.strip()}, {timing}). {summary['days']} days, {summary['first']} to {summary['last']}.",
        name,
        summary,
    )
    return {"name": name, "status": "proposed", **summary}


def list_custom(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Every custom measurement with its SQL and review state, newest first."""
    rows = conn.execute(
        "SELECT name, owner, description, unit, timing, goal, sql, status, review_reason, "
        "created_at FROM research_custom_features ORDER BY created_at DESC"
    ).fetchall()
    keys = (
        "name",
        "owner",
        "description",
        "unit",
        "timing",
        "goal",
        "sql",
        "status",
        "review_reason",
        "created_at",
    )
    return [{k: _jsonable(v) for k, v in zip(keys, r, strict=True)} for r in rows]


def review_custom(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    decision: str,
    reason: str,
    author: str = "methodologist",
) -> dict:
    """The methodologist approves or rejects a proposed measurement.

    Raises:
        TeamError: If the author is not the methodologist, the decision or
            reason is malformed, or the measurement is not awaiting review.
    """
    name = _custom_name(name)
    if author != "methodologist":
        raise TeamError("only the methodologist reviews measurements")
    if decision not in ("approve", "reject") or len(reason.strip()) < 10:
        raise TeamError("decision is approve|reject and reason needs 10+ chars")
    row = conn.execute(
        "SELECT status FROM research_custom_features WHERE name = ?", [name]
    ).fetchone()
    if row is None:
        raise TeamError(f"no measurement {name}")
    if row[0] != "proposed":
        raise TeamError(f"{name} is {row[0]}, not awaiting review")
    status = "approved" if decision == "approve" else "rejected"
    conn.execute(
        "UPDATE research_custom_features SET status = ?, review_reason = ? WHERE name = ?",
        [status, reason.strip(), name],
    )
    research.note(conn, author, "review", f"{status.capitalize()} {name}", reason.strip(), name)
    return {"name": name, "status": status}


def custom_dictionary(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Approved measurements in the data dictionary's row shape.

    A measurement whose SQL now fails is listed as stale with zero days rather
    than dropped, so the failure stays visible.
    """
    today = date.today()
    out = []
    for name, owner, desc, unit, timing in conn.execute(
        "SELECT name, owner, description, unit, timing FROM research_custom_features "
        "WHERE status = 'approved' ORDER BY name"
    ).fetchall():
        try:
            s = custom_series(conn, name)
        except (ValueError, SqlGuardError) as exc:
            log.warning("custom feature %s failed: %s", name, exc)
            s = {}
        last = max(s) if s else None
        out.append(
            {
                "name": name,
                "label": desc,
                "unit": unit,
                "timing": timing,
                "source": f"custom ({owner})",
                "goal": research.goal_of(name, conn),
                "first": str(min(s)) if s else None,
                "last": str(last) if last else None,
                "days": len(s),
                "coverage_90d_pct": round(
                    100 * sum(1 for d in s if d >= today - timedelta(days=90)) / 90
                ),
                "stale": last is None or (today - last).days > 7,
            }
        )
    return out


# ── Agendas ─────────────────────────────────────────────────────────────────


def _text(agenda: dict, key: str) -> str:
    v = agenda.get(key, "")
    if not isinstance(v, str) or len(v) > _MAX_TEXT:
        raise TeamError(f"{key} must be text under {_MAX_TEXT} chars")
    return v.strip()


def _leads(raw: Any, previous: dict[str, str], today: date) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > _MAX_LEADS:
        raise TeamError(f"open_leads must be a list of at most {_MAX_LEADS} leads")
    out, seen = [], set()
    for i, lead in enumerate(raw):
        if not isinstance(lead, dict):
            raise TeamError(f"open_leads[{i}] must be an object")
        extra = set(lead) - {"lead", "why", "priority", "status", "opened"}
        if extra:
            raise TeamError(f"open_leads[{i}] has unknown field(s): {', '.join(sorted(extra))}")
        text, why, pri, status = (
            lead.get("lead"),
            lead.get("why"),
            lead.get("priority"),
            lead.get("status", "open"),
        )
        if not isinstance(text, str) or not text.strip() or len(text) > 300:
            raise TeamError(f"open_leads[{i}].lead must be 1-300 chars")
        if not isinstance(why, str) or not why.strip() or len(why) > 1000:
            raise TeamError(f"open_leads[{i}].why must be 1-1000 chars")
        if isinstance(pri, bool) or not isinstance(pri, int) or not 1 <= pri <= 5:
            raise TeamError(f"open_leads[{i}].priority must be an integer 1-5")
        if status not in LEAD_STATUSES:
            raise TeamError(f"open_leads[{i}].status must be one of {', '.join(LEAD_STATUSES)}")
        key = text.strip()
        if key in seen:
            raise TeamError(f"lead {key!r} appears twice")
        seen.add(key)
        opened = lead.get("opened") or previous.get(key) or today.isoformat()
        try:
            opened = date.fromisoformat(str(opened)[:10]).isoformat()
        except ValueError as exc:
            raise TeamError(f"open_leads[{i}].opened must be an ISO date") from exc
        out.append(
            {"lead": key, "why": why.strip(), "priority": pri, "status": status, "opened": opened}
        )
    return out


def _row_agenda(row: tuple | None) -> dict | None:
    if row is None:
        return None
    return {
        "interests": row[0],
        "open_leads": json.loads(row[1] or "[]"),
        "hunches": row[2],
        "next_steps": row[3],
        "updated_at": _jsonable(row[4]),
    }


def get_agenda(conn: duckdb.DuckDBPyConnection, researcher: str) -> dict | None:
    """One researcher's agenda, or None if they have not written one."""
    return _row_agenda(
        conn.execute(
            "SELECT interests, open_leads, hunches, next_steps, updated_at FROM research_agenda WHERE researcher = ?",
            [researcher],
        ).fetchone()
    )


def _changes(old: dict | None, new: dict) -> list[str]:
    if old is None:
        lines = ["First agenda."]
        lines += [
            f"Opened (P{lead['priority']}, {lead['status']}): {lead['lead']}"
            for lead in new["open_leads"]
        ]
        return lines
    lines = []
    before = {lead["lead"]: lead for lead in old["open_leads"]}
    after = {lead["lead"]: lead for lead in new["open_leads"]}
    for k, lead in after.items():
        prev = before.get(k)
        if prev is None:
            lines.append(f"Opened (P{lead['priority']}, {lead['status']}): {k}")
            continue
        if prev["status"] != lead["status"]:
            lines.append(f"{prev['status']} → {lead['status']}: {k}")
        if prev["priority"] != lead["priority"]:
            lines.append(f"Priority {prev['priority']} → {lead['priority']}: {k}")
    lines += [f"Dropped: {k}" for k in before if k not in after]
    for key, label in (
        ("interests", "Interests"),
        ("hunches", "Hunches"),
        ("next_steps", "Next steps"),
    ):
        if old[key] != new[key]:
            lines.append(f"{label} rewritten.")
    return lines or ["No changes."]


def set_agenda(
    conn: duckdb.DuckDBPyConnection, researcher: str, agenda: dict, today: date | None = None
) -> dict:
    """Replace a researcher's agenda and note what changed.

    Args:
        conn: Write connection.
        researcher: One of RESEARCHERS.
        agenda: ``interests``, ``open_leads``, ``hunches``, ``next_steps``.
            A lead keeps its ``opened`` date across replacements when its text
            is unchanged; a new lead without one opens today.
        today: Override for tests.

    Returns:
        The stored agenda and the change lines written to the notebook.

    Raises:
        TeamError: On an unknown researcher or a malformed agenda.
    """
    if researcher not in RESEARCHERS:
        raise TeamError(f"unknown researcher {researcher!r}")
    extra = set(agenda) - {"interests", "open_leads", "hunches", "next_steps"}
    if extra:
        raise TeamError(f"unknown agenda field(s): {', '.join(sorted(extra))}")
    old = get_agenda(conn, researcher)
    previous = {lead["lead"]: lead["opened"] for lead in (old or {}).get("open_leads", [])}
    new = {
        "interests": _text(agenda, "interests"),
        "open_leads": _leads(agenda.get("open_leads", []), previous, today or date.today()),
        "hunches": _text(agenda, "hunches"),
        "next_steps": _text(agenda, "next_steps"),
    }
    conn.execute(
        "INSERT OR REPLACE INTO research_agenda (researcher, interests, open_leads, hunches, next_steps, updated_at) "
        "VALUES (?, ?, ?, ?, ?, now())",
        [
            researcher,
            new["interests"],
            json.dumps(new["open_leads"]),
            new["hunches"],
            new["next_steps"],
        ],
    )
    changes = _changes(old, new)
    research.note(
        conn,
        researcher,
        "agenda",
        f"{RESEARCHERS[researcher]['name']} agenda updated",
        "\n".join(changes),
        None,
        {"open_leads": len(new["open_leads"])},
    )
    return {**new, "changes": changes}


def team(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Every specialist with their agenda and last notebook activity."""
    activity = {
        r[0]: {"at": _jsonable(r[1]), "kind": r[2], "title": r[3], "entries": r[4]}
        for r in conn.execute(
            "SELECT author, max(written_at), arg_max(kind, written_at), arg_max(title, written_at), count(*) "
            f"FROM research_notebook WHERE author IN ({', '.join('?' * len(RESEARCHERS))}) GROUP BY author",
            list(RESEARCHERS),
        ).fetchall()
    }
    return [
        {
            "researcher": key,
            **meta,
            "agenda": get_agenda(conn, key),
            "last_activity": activity.get(key),
        }
        for key, meta in RESEARCHERS.items()
    ]


# ── Explorations ────────────────────────────────────────────────────────────


def record_exploration(
    conn: duckdb.DuckDBPyConnection,
    author: str,
    title: str,
    looked_at: str,
    numbers: str,
    lead: str = "",
    lead_effect: str = "neither",
) -> str:
    """Write a free exploration to the notebook. Never touches beliefs or the engine.

    Args:
        conn: Write connection.
        author: The specialist who explored.
        title: One-line headline.
        looked_at: What data, query or measurement was examined.
        numbers: The numbers found, with units.
        lead: The lead this opens or closes, if any.
        lead_effect: ``opens``, ``closes`` or ``neither``.

    Returns:
        The notebook entry id.

    Raises:
        TeamError: On an unknown author or missing fields.
    """
    if author not in RESEARCHERS:
        raise TeamError(f"author must be one of {', '.join(RESEARCHERS)}")
    if lead_effect not in ("opens", "closes", "neither"):
        raise TeamError("lead_effect must be opens, closes or neither")
    if lead_effect != "neither" and not lead.strip():
        raise TeamError(f"name the lead this {lead_effect}")
    fields = {"title": title, "looked_at": looked_at, "numbers": numbers}
    for k, v in fields.items():
        if not v.strip() or len(v) > _MAX_TEXT:
            raise TeamError(f"{k} must be 1-{_MAX_TEXT} chars")
    body = f"Looked at: {looked_at.strip()}\nFound: {numbers.strip()}"
    if lead_effect != "neither":
        body += f"\n{lead_effect.capitalize()} lead: {lead.strip()}"
    return research.note(
        conn,
        author,
        "exploration",
        title.strip(),
        body,
        None,
        {
            **{k: v.strip() for k, v in fields.items()},
            "lead": lead.strip(),
            "lead_effect": lead_effect,
        },
    )
