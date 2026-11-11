from __future__ import annotations

from datetime import date, timedelta

from shc.api.routers.dashboard import court_kcal_7d, window_shift

END = date(2026, 3, 31)


def test_window_shift_compares_the_lagged_window():
    s = {END - timedelta(days=i): (100.0 if i < 28 else 200.0) for i in range(200)}
    assert window_shift(s, END) == (100.0, 200.0)


def test_window_shift_skips_missing_days_instead_of_zeroing_them():
    s = {END: 300.0, END - timedelta(days=5): 100.0}
    assert window_shift(s, END) == (200.0, None)


def test_court_kcal_spreads_a_session_over_its_week():
    out = court_kcal_7d({END: 700.0}, END - timedelta(days=1), END + timedelta(days=7))
    assert out[END - timedelta(days=1)] == 0.0
    assert out[END] == 100.0
    assert out[END + timedelta(days=6)] == 100.0
    assert out[END + timedelta(days=7)] == 0.0
