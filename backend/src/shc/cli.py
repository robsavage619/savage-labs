from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, date, datetime, timedelta

import click

from shc.config import settings
from shc.db.schema import init_db, write_ctx


@click.group()
def main() -> None:
    pass


@main.command()
def reconcile() -> None:
    """Compare what the engine SAYS against what the raw rows SHOW.

    Independent recomputation from the rawest available data — not a re-run of
    the engine's own helpers, which would prove nothing. Exists because on
    2026-07-26 a green 719-test suite sat on top of a dozen live calculation
    defects; unit tests assert a function does what its author believed, and
    every one of those defects was a belief that was wrong.
    """
    from shc.db.schema import get_read_conn, init_db
    from shc.training.reconcile import run_all

    init_db()  # the CLI has no app lifespan to open the connection for it
    conn = get_read_conn()
    try:
        findings = run_all(conn)
    finally:
        conn.close()
    for f in findings:
        click.echo(("  OK   " if f.ok else "  FAIL ") + f"{f.check:<44}{f.detail}")
        for r in f.rows[:10]:
            click.echo(f"           - {r}")
    clean = sum(f.ok for f in findings)
    click.echo(f"\n{clean}/{len(findings)} checks clean")
    if clean != len(findings):
        raise SystemExit(1)


@main.command()
@click.option("--days", default=90, show_default=True, help="Days of demo data to seed")
def seed(days: int) -> None:
    """Populate DuckDB with synthetic WHOOP+sleep data for UI development."""
    asyncio.run(_seed(days))
    click.echo(f"Seeded {days} days of demo data.")


async def _seed(days: int) -> None:
    init_db()
    today = date.today()
    async with write_ctx() as conn:
        for i in range(days):
            d = today - timedelta(days=days - i)
            hrv = round(random.gauss(65, 12), 1)
            rhr = random.randint(48, 60)
            score = max(1, min(100, int(random.gauss(72, 15))))
            rec_id = f"seed_rec_{d}"
            conn.execute(
                "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) "
                "VALUES ($id, 'whoop', $date, $score, $hrv, $rhr, 'seed') "
                "ON CONFLICT DO NOTHING",
                {"id": rec_id, "date": d.isoformat(), "score": score, "hrv": hrv, "rhr": rhr},
            )

            sleep_h = round(random.gauss(7.2, 0.8), 2)
            ts_in = datetime.combine(d - timedelta(days=1), datetime.min.time()).replace(
                hour=23, minute=random.randint(0, 59), tzinfo=UTC
            )
            ts_out = ts_in + timedelta(hours=sleep_h)
            stages = json.dumps(
                {
                    "deep_min": int(sleep_h * 60 * 0.15),
                    "rem_min": int(sleep_h * 60 * 0.22),
                    "light_min": int(sleep_h * 60 * 0.5),
                    "awake_min": int(sleep_h * 60 * 0.13),
                }
            )
            conn.execute(
                "INSERT INTO sleep (id, source, night_date, ts_in, ts_out, stages_json, "
                "spo2_avg, rhr, hrv, content_hash) "
                "VALUES ($id, 'whoop', $night, $tin, $tout, $stages, $spo2, $rhr, $hrv, 'seed') "
                "ON CONFLICT DO NOTHING",
                {
                    "id": f"seed_sleep_{d}",
                    "night": d.isoformat(),
                    "tin": ts_in.isoformat(),
                    "tout": ts_out.isoformat(),
                    "stages": stages,
                    "spo2": round(random.gauss(96.5, 0.8), 1),
                    "rhr": rhr,
                    "hrv": hrv,
                },
            )


@main.command("ingest-fitbod")
@click.option(
    "--csv", "csv_path", default=None, help="Path to WorkoutExport.csv (auto-detected if omitted)"
)
@click.option(
    "--rebuild", is_flag=True, help="Wipe existing Fitbod data and re-ingest from scratch"
)
def ingest_fitbod(csv_path: str | None, rebuild: bool) -> None:
    """Ingest Fitbod WorkoutExport.csv into workouts + workout_sets + working_weights."""
    from pathlib import Path

    from shc.config import settings
    from shc.ingest.fitbod import ingest_fitbod as _ingest

    init_db()
    path = Path(csv_path) if csv_path else settings.fitbod_csv_path
    click.echo(f"Loading Fitbod data from {path} ...")
    if rebuild:
        click.echo("Rebuild mode: wiping existing Fitbod rows before re-ingest.")
    result = _ingest(path, rebuild=rebuild)
    click.echo(
        f"Done: {result['workouts_inserted']} new sessions, {result['sets_inserted']} new sets "
        f"({result['sessions']} total sessions in CSV, {result['skipped']} skipped)"
    )


@main.command("ingest-whoop-journal")
@click.option(
    "--csv", "csv_path", default=None, help="Path to journal_entries.csv (auto-detected if omitted)"
)
def ingest_whoop_journal_cmd(csv_path: str | None) -> None:
    """Ingest a WHOOP export journal_entries.csv into whoop_journal."""
    from pathlib import Path

    from shc.config import settings
    from shc.ingest.whoop_journal import ingest_whoop_journal as _ingest

    init_db()
    path = Path(csv_path) if csv_path else settings.whoop_journal_csv_path
    click.echo(f"Loading WHOOP journal from {path} ...")
    result = _ingest(path)
    click.echo(
        f"Done: {result['inserted']} inserted, {result['updated']} updated, "
        f"{result['skipped']} skipped ({result['rows']} rows in CSV)"
    )
    for warning in result["skipped_detail"]:
        click.echo(f"  skipped {warning}")


@main.command("ingest-clinical-profile")
@click.option("--yaml", "yaml_path", default=None, help="Path to clinical_profile.yml")
def ingest_clinical_profile_cmd(yaml_path: str | None) -> None:
    """Load Rob's clinical profile (conditions, meds, labs, vitals) from YAML."""
    from pathlib import Path

    from shc.ingest.clinical_profile import ingest_clinical_profile as _ingest

    init_db()
    path = Path(yaml_path) if yaml_path else None
    click.echo("Loading clinical profile ...")
    result = _ingest(path)
    click.echo(
        f"Done: {result['conditions']} conditions, {result['medications']} meds, "
        f"{result['labs']} labs, {result['vitals']} vitals."
    )


@main.command()
@click.confirmation_option(prompt="This will delete and recreate the database. Are you sure?")
def reset() -> None:
    """Delete DuckDB and re-apply migrations with fresh seed data."""
    db = settings.db_path
    if db.exists():
        db.unlink()
        click.echo(f"Deleted {db}")
    asyncio.run(_seed(90))
    click.echo("Database reset and seeded.")


@main.group("whoop-private")
def whoop_private() -> None:
    """WHOOP private-iOS-API commands (Journal backfill).

    Separate from the OAuth sync: this surface is not sanctioned by WHOOP and is
    run deliberately, on demand, rather than on the scheduler.
    """


@whoop_private.command("login")
@click.option("--email", prompt="WHOOP email", help="WHOOP account email")
def whoop_private_login(email: str) -> None:
    """Establish a private-API session. Prompts for password + MFA; neither is stored."""
    from shc.ingest.whoop_private import login

    password = click.prompt("WHOOP password", hide_input=True)

    def mfa_prompt(destination: str) -> str:
        label = f" (sent to {destination})" if destination else ""
        return str(click.prompt(f"MFA code{label}")).strip()

    asyncio.run(login(email, password, mfa_prompt))
    click.echo("Private-API session established — tokens stored in Keychain.")


@whoop_private.command("sync-journal")
@click.option("--days", default=30, show_default=True, help="Calendar days to walk back")
def whoop_private_sync_journal(days: int) -> None:
    """Backfill whoop_journal from the private API."""
    from shc.ingest.whoop_journal import sync_journal_api

    init_db()
    click.echo(f"Pulling WHOOP journal for the last {days} days ...")
    result = asyncio.run(sync_journal_api(days))
    click.echo(
        f"Done: {result['inserted']} inserted, {result['updated']} updated, "
        f"{result['entries_seen']} entries seen"
    )
    if result["collisions"]:
        click.echo(f"  {result['collisions']} skipped — already covered by the CSV export:")
        for detail in result["collision_detail"][:10]:
            click.echo(f"    {detail}")
    if result["unknown_tracker_ids"]:
        click.echo(f"  unknown tracker IDs (not in catalog): {result['unknown_tracker_ids'][:20]}")
    if result["failed_dates"]:
        click.echo(f"  {len(result['failed_dates'])} dates failed to fetch")
