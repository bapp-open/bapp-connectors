"""Calendarul fiscal Apple (luni de 5-4-4 saptamani, calculate din regula)."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import pytest

from bapp_connectors.providers.appstore.apple.fiscal_calendar import (
    apple_report_date,
    fiscal_months,
    fiscal_period_for,
    fiscal_periods_between,
    fiscal_range,
    payment_date,
    period_from_apple_report_date,
)

#: FY2026, verificat pe calendarul din App Store Connect (tabel de regresie)
FY2026 = {
    "2025-10": (date(2025, 9, 28), date(2025, 11, 1)),
    "2025-11": (date(2025, 11, 2), date(2025, 11, 29)),
    "2025-12": (date(2025, 11, 30), date(2025, 12, 27)),
    "2026-01": (date(2025, 12, 28), date(2026, 1, 31)),
    "2026-02": (date(2026, 2, 1), date(2026, 2, 28)),
    "2026-03": (date(2026, 3, 1), date(2026, 3, 28)),
    "2026-04": (date(2026, 3, 29), date(2026, 5, 2)),
    "2026-05": (date(2026, 5, 3), date(2026, 5, 30)),
    "2026-06": (date(2026, 5, 31), date(2026, 6, 27)),
    "2026-07": (date(2026, 6, 28), date(2026, 8, 1)),
    "2026-08": (date(2026, 8, 2), date(2026, 8, 29)),
    "2026-09": (date(2026, 8, 30), date(2026, 9, 26)),
}

#: FY2027, derivat din regula (52 de saptamani, se incheie sambata 2027-09-25)
FY2027 = {
    "2026-10": (date(2026, 9, 27), date(2026, 10, 31)),
    "2026-11": (date(2026, 11, 1), date(2026, 11, 28)),
    "2026-12": (date(2026, 11, 29), date(2026, 12, 26)),
    "2027-01": (date(2026, 12, 27), date(2027, 1, 30)),
    "2027-02": (date(2027, 1, 31), date(2027, 2, 27)),
    "2027-03": (date(2027, 2, 28), date(2027, 3, 27)),
    "2027-04": (date(2027, 3, 28), date(2027, 5, 1)),
    "2027-05": (date(2027, 5, 2), date(2027, 5, 29)),
    "2027-06": (date(2027, 5, 30), date(2027, 6, 26)),
    "2027-07": (date(2027, 6, 27), date(2027, 7, 31)),
    "2027-08": (date(2027, 8, 1), date(2027, 8, 28)),
    "2027-09": (date(2027, 8, 29), date(2027, 9, 25)),
}


def test_fy2026_regression_table():
    assert fiscal_months(2026) == FY2026
    for period, expected in FY2026.items():
        assert fiscal_range(period) == expected


def test_fy2027_derived_from_rule():
    assert fiscal_months(2027) == FY2027


def test_53_week_year_puts_extra_week_in_december():
    months = fiscal_months(2023)
    assert months["2022-10"][0] == date(2022, 9, 25)
    assert months["2023-09"][1] == date(2023, 9, 30)
    assert months["2022-12"] == (date(2022, 11, 27), date(2022, 12, 31))
    assert months["2023-01"][0] == date(2023, 1, 1)


def test_day_maps_to_period():
    assert fiscal_period_for(date(2026, 9, 26)) == "2026-09"
    assert fiscal_period_for(date(2026, 9, 27)) == "2026-10"
    assert fiscal_period_for(date(2025, 9, 28)) == "2025-10"
    assert fiscal_period_for(date(2022, 12, 31)) == "2022-12"


def test_history_is_covered():
    assert fiscal_period_for(date(2020, 1, 1)) == "2020-01"
    assert fiscal_period_for(date(2010, 1, 15)) == "2010-01"


def test_periods_between_crosses_fiscal_year_boundary():
    assert fiscal_periods_between(date(2026, 9, 20), date(2026, 10, 5)) == ["2026-09", "2026-10"]
    assert fiscal_periods_between(date(2026, 9, 1), date(2026, 9, 2)) == ["2026-09"]


def test_months_are_contiguous_without_gaps_2015_2030():
    ranges: list[tuple[str, date, date]] = []
    for fiscal_year in range(2015, 2031):
        ranges.extend((period, start, end) for period, (start, end) in fiscal_months(fiscal_year).items())
    for (prev_label, _ps, prev_end), (label, start, _e) in pairwise(ranges):
        assert start == prev_end + timedelta(days=1), (prev_label, label)
        assert label > prev_label
    for _label, start, end in ranges:
        assert start.weekday() == 6  # duminica
        assert end.weekday() == 5  # sambata


def test_nonsense_inputs_raise_value_error():
    with pytest.raises(ValueError):
        fiscal_period_for(date(2005, 1, 1))
    with pytest.raises(ValueError):
        fiscal_range("2026-13")
    with pytest.raises(ValueError):
        fiscal_range("nope")


def test_payment_date_is_33_days_after_period_end():
    assert payment_date("2026-08") == date(2026, 10, 1)
    assert payment_date("2026-09") == date(2026, 10, 29)
    assert payment_date("garbage") is None


@pytest.mark.parametrize(
    ("label", "report_date"),
    [
        ("2024-09", "2024-12"),
        ("2024-10", "2025-01"),
        ("2024-11", "2025-02"),
        ("2025-01", "2025-04"),
        ("2025-09", "2025-12"),
        ("2025-10", "2026-01"),
        ("2026-09", "2026-12"),
    ],
)
def test_apple_report_date_translation(label, report_date):
    assert apple_report_date(label) == report_date
    assert period_from_apple_report_date(report_date) == label


def test_apple_report_date_round_trips_every_fiscal_month():
    for fiscal_year in (2024, 2025, 2026):
        for label in fiscal_months(fiscal_year):
            assert period_from_apple_report_date(apple_report_date(label)) == label
