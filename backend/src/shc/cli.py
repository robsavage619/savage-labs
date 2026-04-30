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
@click.option("--csv", "csv_path", default=None, help="Path to WorkoutExport.csv (auto-detected if omitted)")
@click.option("--rebuild", is_flag=True, help="Wipe existing Fitbod data and re-ingest from scratch")
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
    click.echo(f"Done: {result['workouts_inserted']} new sessions, {result['sets_inserted']} new sets "
               f"({result['sessions']} total sessions in CSV, {result['skipped']} skipped)")


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
