from __future__ import annotations

from datetime import date

import duckdb
import pytest

from shc.ingest import whoop_private_metrics as m
from shc.ingest.whoop_private import WHOOPPrivateSchemaError

END = date(2026, 11, 15)


def _point(label: str | None, shown: str | None) -> dict:
    return {"data_scrubber_details": {"primary_contextual_display": label, "value_display": shown}}


def _segment(*points: dict, trend_label: str = "99") -> dict:
    return {
        "graph": {
            "plots": [
                {"type": "LINE_PLOT", "plot": {"segments": [{"points": list(points)}]}},
                {"type": "TREND_PLOT", "plot": {"segments": [{"top_label": trend_label}]}},
            ]
        }
    }


def test_labels_without_a_year_resolve_to_the_latest_matching_date() -> None:
    assert m._label_date("TUE, NOV 10", END) == date(2026, 11, 10)
    # Across New Year the same label belongs to the year before.
    assert m._label_date("TUE, DEC 30", date(2026, 1, 6)) == date(2025, 12, 30)
    # A weekday that fits neither year is dropped, not filed under a guess.
    assert m._label_date("WED, NOV 10", END) is None
    assert m._label_date("TUE, NOV 17", END) is None  # after the end date
    assert m._label_date("not a label", END) is None
    assert m._label_date(None, END) is None


def test_weekly_points_are_read_from_the_line_plot_across_windows() -> None:
    payload = {
        "six_month_time_segment": _segment(
            _point("TUE, OCT 27", "37"), _point("TUE, NOV 3", "36"), _point("TUE, NOV 10", None)
        ),
        # The shorter window only fills the gap the longer one left; it never overrides.
        "month_time_segment": _segment(_point("TUE, NOV 10", "35"), _point("TUE, NOV 3", "99")),
        "week_time_segment": _segment(_point("TUE, NOV 10", "34")),
    }
    got = m._vo2_points(payload, END)
    assert got == {date(2026, 10, 27): 37.0, date(2026, 11, 3): 36.0, date(2026, 11, 10): 35.0}


def test_an_implausible_value_is_dropped_not_stored() -> None:
    payload = {
        "week_time_segment": _segment(_point("TUE, NOV 10", "35"), _point("TUE, NOV 3", "4"))
    }
    assert m._vo2_points(payload, END) == {date(2026, 11, 10): 35.0}


def test_a_changed_response_shape_fails_loudly_instead_of_reading_as_no_data() -> None:
    with pytest.raises(WHOOPPrivateSchemaError, match="no time segments"):
        m._vo2_points({"metadata": {}}, END)
    unparsable = {"month_time_segment": _segment(_point("garbled", "35"), _point(None, None))}
    with pytest.raises(WHOOPPrivateSchemaError, match="none parsed"):
        m._vo2_points(unparsable, END)
    # A window with no points is an honest "no data yet", not an error.
    assert m._vo2_points({"week_time_segment": _segment()}, END) == {}


def test_weekly_estimates_land_as_their_own_series_and_restatements_update(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    m._upsert_vo2(conn, {date(2026, 11, 3): 36.0, date(2026, 11, 10): 35.0})
    m._upsert_vo2(conn, {date(2026, 11, 10): 34.0})  # WHOOP restated the latest week
    rows = conn.execute(
        "SELECT date, source, metric, value_avg FROM v_daily_metrics "
        "WHERE metric LIKE 'vo2_max%' ORDER BY date"
    ).fetchall()
    assert rows == [
        (date(2026, 11, 3), "whoop_private", "vo2_max_whoop", 36.0),
        (date(2026, 11, 10), "whoop_private", "vo2_max_whoop", 34.0),
    ]
