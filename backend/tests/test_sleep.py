from __future__ import annotations

from datetime import date, datetime

from shc.metrics import _sleep


def test_empty_returns_blank_metrics(conn, today: date) -> None:
    m = _sleep(conn, today)
    assert m.last_hours is None
    assert m.score is None


def test_basic_night_hours_and_stage_percentages(conn, seed, today: date) -> None:
    # 7h asleep: deep 84, rem 42, light 294 (total 420 min = 7h).
    seed.sleep(
        today,
        datetime(2026, 5, 19, 23, 0),
        datetime(2026, 5, 20, 6, 0),
        sws_min=84, rem_min=42, light_min=294, awake_min=18,
        sleep_cycle_count=5, disturbance_count=4,
    )
    seed.recovery(today, spo2=96.0)
    m = _sleep(conn, today)
    assert m.last_hours == 7.0
    assert m.deep_min_last == 84.0
    assert m.deep_pct_last == round(84 / 420, 3)   # 0.2
    assert m.rem_pct_last == round(42 / 420, 3)
    assert m.spo2_avg_last == 96.0
    assert m.sleep_cycle_count_last == 5
    assert m.score is not None  # _sleep_subscore ran


def test_collapses_split_records_to_longest(conn, seed, today: date) -> None:
    # WHOOP sometimes splits a night; the builder keeps the longest segment.
    seed.sleep(today, datetime(2026, 5, 19, 23, 0), datetime(2026, 5, 20, 0, 30))  # 1.5h
    seed.sleep(today, datetime(2026, 5, 20, 1, 0), datetime(2026, 5, 20, 7, 0))    # 6h
    m = _sleep(conn, today)
    assert m.last_hours == 6.0


def test_naps_excluded(conn, seed, today: date) -> None:
    seed.sleep(today, datetime(2026, 5, 20, 13, 0), datetime(2026, 5, 20, 13, 30),
               is_nap=True)
    m = _sleep(conn, today)
    assert m.last_hours is None


def test_latest_night_is_used(conn, seed, today: date) -> None:
    seed.sleep(date(2026, 5, 18), datetime(2026, 5, 17, 23, 0),
               datetime(2026, 5, 18, 5, 0))  # 6h, older
    seed.sleep(today, datetime(2026, 5, 19, 22, 0),
               datetime(2026, 5, 20, 6, 0))   # 8h, last night
    m = _sleep(conn, today)
    assert m.last_hours == 8.0


def test_spo2_comes_from_recovery_not_sleep(conn, seed, today: date) -> None:
    # Whoop's sleep endpoint omits spo2_percentage, so the ingest always writes
    # sleep.spo2_avg = NULL. Reading that column silently drops every reading:
    # Rob has diagnosed OSA and 880+ nights of oximetry that reached nothing.
    seed.sleep(today, datetime(2026, 5, 19, 23, 0), datetime(2026, 5, 20, 6, 0),
               sws_min=84, rem_min=42, light_min=294, spo2_avg=None)
    seed.recovery(today, spo2=93.4)
    m = _sleep(conn, today)
    assert m.spo2_avg_last == 93.4


def test_spo2_absent_when_recovery_missing(conn, seed, today: date) -> None:
    # LEFT JOIN: a night with sleep but no recovery row must not raise.
    seed.sleep(today, datetime(2026, 5, 19, 23, 0), datetime(2026, 5, 20, 6, 0),
               sws_min=84, rem_min=42, light_min=294)
    m = _sleep(conn, today)
    assert m.spo2_avg_last is None
    assert m.last_hours == 7.0


def test_spo2_reaches_the_sleep_score(conn, seed, today: date) -> None:
    # spo2 carries 20% of the composite; a desaturating night must score below
    # an identical night with normal oxygen, or the signal is decorative.
    seed.sleep(today, datetime(2026, 5, 19, 23, 0), datetime(2026, 5, 20, 6, 0),
               sws_min=84, rem_min=42, light_min=294)
    seed.recovery(today, spo2=97.0)
    good = _sleep(conn, today).score

    conn.execute("DELETE FROM recovery")
    seed.recovery(today, spo2=90.0)
    bad = _sleep(conn, today).score

    assert good is not None and bad is not None
    assert bad < good
