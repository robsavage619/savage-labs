from __future__ import annotations

from datetime import date, timedelta

from shc.metrics import _training_load


def ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


def test_empty_defaults(conn, today: date) -> None:
    m = _training_load(conn, today)
    assert m.acwr is None
    assert m.days_since_legs == 99
    assert m.days_since_push == 99
    assert m.days_since_pull == 99
    assert m.push_pull_ratio_28d is None


def test_acwr_high_when_recent_load_spikes(conn, seed, today: date) -> None:
    # composite_load = hevy_volume_kg / 5000 (no WHOOP strain seeded).
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(50, 10)])     # vol 500
    seed.workout(ago(today, 2), "Bench Press (Barbell)", [(200, 50)])     # vol 10000
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr > 1.5  # acute window carries the spike


def test_acwr_low_when_no_recent_load(conn, seed, today: date) -> None:
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(200, 50)])    # only old
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr < 0.8


def test_days_since_muscle_groups(conn, seed, today: date) -> None:
    seed.workout(ago(today, 1), "Bench Press (Barbell)", [(80, 8)])   # push
    seed.workout(ago(today, 5), "Bent Over Row (Barbell)", [(80, 8)])  # pull
    m = _training_load(conn, today)
    assert m.days_since_push == 1
    assert m.days_since_pull == 5
    assert m.days_since_legs == 99  # never trained


def test_push_pull_ratio(conn, seed, today: date) -> None:
    seed.workout(ago(today, 3), "Bench Press (Barbell)",
                 [(80, 8), (80, 8), (80, 8), (80, 8)])  # 4 push sets
    seed.workout(ago(today, 4), "Bent Over Row (Barbell)",
                 [(80, 8), (80, 8)])                     # 2 pull sets
    m = _training_load(conn, today)
    assert m.push_sets_28d == 4
    assert m.pull_sets_28d == 2
    assert m.push_pull_ratio_28d == 2.0


def test_pickleball_has_own_clock_not_legs(conn, seed, today: date) -> None:
    """Pickleball is conditioning — it must NOT reset the legs lifting clock
    (it used to, which rest-gated leg lifting for any weekend court player)."""
    seed.cardio(ago(today, 2), "pickleball", 90)
    m = _training_load(conn, today)
    assert m.days_since_legs == 99  # no leg LIFT on record
    assert m.days_since_pickleball == 2
    assert m.pickleball_min_28d == 90


def test_legs_clock_tracks_lifts_only(conn, seed, today: date) -> None:
    seed.cardio(ago(today, 6), "pickleball", 90)
    seed.workout(ago(today, 1), "Goblet Squat", [(40, 10)])  # legs lift yesterday
    m = _training_load(conn, today)
    assert m.days_since_legs == 1
    assert m.days_since_pickleball == 6


def test_arm_acwr_resistance_and_conditioning_are_independent(
    conn, seed, today: date
) -> None:
    """Resistance (Hevy tonnes, idx 3) and conditioning (WHOOP strain, idx 2) are
    independent ACWR streams — a spike in one must not move the other."""
    import uuid
    from datetime import datetime

    def _whoop(days_ago: int, strain: float) -> None:
        wid = str(uuid.uuid4())
        started = datetime.combine(ago(today, days_ago), datetime.min.time())
        conn.execute(
            "INSERT INTO workouts (id, source, started_at, kind, strain, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [wid, "whoop", started, "running", strain, wid],
        )

    # Chronic conditioning baseline: low strain 15 days ago.
    _whoop(15, 8.0)
    # Acute conditioning spike: high strain 3 days ago.
    _whoop(3, 18.5)

    # Hevy lifting only in the chronic window; no acute Hevy load.
    seed.workout(ago(today, 15), "Bench Press (Barbell)", [(80, 10)] * 5)

    m = _training_load(conn, today)

    # Conditioning arm: recent 18.5 spike > chronic 8.0 baseline → ACWR > 1.
    assert m.conditioning_acwr is not None
    assert m.conditioning_acwr > 1.0, "conditioning spike should raise cond. ACWR"

    # Resistance arm: acute is 0 (no Hevy this week), chronic has the old lift → ACWR < 1.
    assert m.resistance_acwr is not None
    assert m.resistance_acwr < 1.0, "resistance acute should be 0 with no recent lift"
