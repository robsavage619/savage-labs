from __future__ import annotations

from datetime import date, datetime, timedelta

from shc.metrics import _checkin, _recovery, _training_load


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
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(50, 10)])  # vol 500
    seed.workout(ago(today, 2), "Bench Press (Barbell)", [(200, 50)])  # vol 10000
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr > 1.5  # acute window carries the spike


def test_acwr_low_when_no_recent_load(conn, seed, today: date) -> None:
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(200, 50)])  # only old
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr < 0.8


def test_acwr_equals_one_under_constant_load(conn, seed, today: date) -> None:
    # Window-exactness guard: equal load every day for 28 days means the 7-day
    # acute mean equals the 21-day chronic mean, so ACWR must be EXACTLY 1.0. The
    # prior off-by-one (acute >= today-7 → 8 day-slots / 7) made this read ~1.14.
    for n in range(28):
        seed.workout(ago(today, n), "Bench Press (Barbell)", [(100, 10)])
    m = _training_load(conn, today)
    assert m.acwr == 1.0


def test_acwr_excludes_day_seven_from_acute(conn, seed, today: date) -> None:
    # A single bout exactly 7 days ago belongs to the CHRONIC window now, not the
    # acute one. With acute load = 0 the ratio is 0 (or near-0), never elevated.
    seed.workout(ago(today, 7), "Bench Press (Barbell)", [(200, 50)])
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr < 0.2  # day-7 load is chronic; acute window is empty


def test_days_since_muscle_groups(conn, seed, today: date) -> None:
    seed.workout(ago(today, 1), "Bench Press (Barbell)", [(80, 8)])  # push
    seed.workout(ago(today, 5), "Bent Over Row (Barbell)", [(80, 8)])  # pull
    m = _training_load(conn, today)
    assert m.days_since_push == 1
    assert m.days_since_pull == 5
    assert m.days_since_legs == 99  # never trained


def test_push_pull_ratio(conn, seed, today: date) -> None:
    seed.workout(
        ago(today, 3), "Bench Press (Barbell)", [(80, 8), (80, 8), (80, 8), (80, 8)]
    )  # 4 push sets
    seed.workout(ago(today, 4), "Bent Over Row (Barbell)", [(80, 8), (80, 8)])  # 2 pull sets
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


def test_arm_acwr_resistance_and_conditioning_are_independent(conn, seed, today: date) -> None:
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


# ── Windowed queries must anchor to `today`, not SQL current_date ─────────────
# The `today` fixture (2026-05-20) is ~30 days before the real wall-clock date,
# so data seeded relative to `today` falls outside any current_date-anchored
# window. These lock in that backtests/recompute see the same numbers as live.


def test_cardio_min_28d_anchors_to_today(conn, seed, today: date) -> None:
    # 10 days before `today` → inside today's 28d window, but well before the
    # real-date 28d window (~30 days later), where it would wrongly read 0.
    seed.cardio(ago(today, 10), "running", 45)
    m = _training_load(conn, today)
    assert m.cardio_min_28d == 45


def test_z2_7d_fallback_anchors_to_today(conn, seed, today: date) -> None:
    # No WHOOP zone data → HR-range fallback. max_hr defaults to 180 → Z2 = 108–126.
    # 3 days before `today` is inside today's 7d window, outside the real-date one.
    seed.cardio(ago(today, 3), "running", 30, avg_hr=115)
    m = _training_load(conn, today)
    assert m.cardio_z2_min_7d == 30


def test_skin_temp_baseline_anchors_to_today(conn, today: date) -> None:
    import uuid

    # 14 nights (>= BASELINE_MIN_N) ending the day before `today`, all inside
    # today's 28d window but before the real-date window.
    for n in range(1, 15):
        rid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO recovery (id, source, date, skin_temp, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            [rid, "whoop", ago(today, n), 33.0, rid],
        )
    m = _recovery(conn, today)
    assert m.skin_temp_baseline_28d == 33.0  # None if window anchored to current_date


def test_body_weight_trend_anchors_to_today(conn, today: date) -> None:
    def _weight(days_ago: int, kg: float) -> None:
        ts = datetime.combine(ago(today, days_ago), datetime.min.time())
        conn.execute(
            "INSERT INTO measurements "
            "(source, metric, ts, value_num, external_id, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ["whoop", "body_mass_kg", ts, kg, f"w{days_ago}", f"w{days_ago}"],
        )

    _weight(1, 80.0)  # latest weight
    _weight(40, 100.0)  # past anchor: only qualifies if cutoff = today - 28d
    m = _checkin(conn, today)
    # current_date cutoff (~today+30 − 28d) would pick the recent 80 → ~0%.
    assert m.body_weight_trend_4wk == -20.0
