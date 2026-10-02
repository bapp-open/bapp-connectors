"""Calendarul fiscal Apple (luni de 4-4-5 saptamani)."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

import pytest

from bapp_connectors.providers.appstore.apple.fiscal_calendar import (
    FISCAL_MONTHS,
    fiscal_period_for,
    fiscal_periods_between,
    fiscal_range,
    payment_date,
)


def test_known_periods():
    assert fiscal_range("2026-09") == (date(2026, 8, 30), date(2026, 9, 26))
    assert fiscal_range("2026-10") == (date(2026, 9, 27), date(2026, 10, 31))


def test_day_maps_to_period():
    assert fiscal_period_for(date(2026, 9, 26)) == "2026-09"
    assert fiscal_period_for(date(2026, 9, 27)) == "2026-10"
    assert fiscal_period_for(date(2025, 9, 28)) == "2025-10"


def test_periods_between_crosses_fiscal_year_boundary():
    assert fiscal_periods_between(date(2026, 9, 20), date(2026, 10, 5)) == ["2026-09", "2026-10"]
    assert fiscal_periods_between(date(2026, 9, 1), date(2026, 9, 2)) == ["2026-09"]


def test_months_are_contiguous_without_gaps():
    periods = sorted(FISCAL_MONTHS)
    for previous, current in pairwise(periods):
        assert FISCAL_MONTHS[current][0] == FISCAL_MONTHS[previous][1] + timedelta(days=1), (previous, current)


def test_calendar_covers_next_six_months():
    """Pica cu ~6 luni inainte sa ramanem fara calendar, ca cineva sa adauge anul fiscal urmator."""
    horizon = date.today() + timedelta(days=180)
    assert fiscal_period_for(horizon)


def test_unknown_day_raises():
    with pytest.raises(KeyError):
        fiscal_period_for(date(2020, 1, 1))


def test_payment_date_is_33_days_after_period_end():
    assert payment_date("2026-08") == date(2026, 10, 1)
    assert payment_date("2026-09") == date(2026, 10, 29)
