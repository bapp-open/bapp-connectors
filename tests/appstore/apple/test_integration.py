"""Integrare Apple pe contul real (cere BAPP_APPLE_*). Nu scrie nimic in cont."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.appstore.apple.fiscal_calendar import fiscal_period_for
from tests.appstore.conftest import APPLE_APP_ID, APPLE_ENV, skip_unless_apple

pytestmark = [pytest.mark.integration, skip_unless_apple]


@pytest.fixture(scope="module")
def adapter():
    import bapp_connectors.providers.appstore.apple  # noqa: F401

    return registry.create_adapter("appstore", "apple", credentials=APPLE_ENV)


def test_connection(adapter):
    assert adapter.test_connection().success is True


def test_list_apps(adapter):
    apps = adapter.list_apps()
    assert apps and all(a.bundle_id for a in apps)


def test_last_week_sales(adapter):
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=6)
    cursor, total = None, Decimal("0")
    while True:
        page = adapter.get_sales(start, end, cursor)
        total += sum(s.proceeds_total for s in page.items)
        if not page.has_more:
            break
        cursor = page.cursor
    print(f"Apple proceeds {start}..{end}: {total}")  # noqa: T201 — pentru comparatia manuala cu Sales and Trends


def test_last_closed_fiscal_month_net(adapter):
    period = fiscal_period_for(date.today() - timedelta(days=45))
    page = adapter.get_financial_transactions(datetime.now() - timedelta(days=45), datetime.now() - timedelta(days=45))
    by_currency: dict[str, Decimal] = {}
    for t in page.items:
        by_currency[t.currency] = by_currency.get(t.currency, Decimal("0")) + t.net_amount
    print(f"Apple FINANCE_DETAIL {period}: {by_currency}")  # noqa: T201 — se compara cu Payments and Financial Reports
    assert all(t.payout_id.startswith(period) for t in page.items)


def test_reviews(adapter):
    if not APPLE_APP_ID:
        pytest.skip("BAPP_APPLE_APP_ID lipseste")
    page = adapter.list_reviews(APPLE_APP_ID)
    assert all(1 <= (r.rating or 1) <= 5 for r in page.items)
