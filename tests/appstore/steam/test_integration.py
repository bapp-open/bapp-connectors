"""Integrare Steam pe contul real (cere BAPP_STEAM_*). Nu scrie nimic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import AppStoreStat, AppStoreStatMetric, FinancialTransactionType
from bapp_connectors.core.registry import registry
from tests.appstore.conftest import STEAM_ENV, skip_unless_steam

pytestmark = [pytest.mark.integration, skip_unless_steam]


@pytest.fixture(scope="module")
def adapter():
    import bapp_connectors.providers.appstore.steam  # noqa: F401

    return registry.create_adapter("appstore", "steam", credentials=STEAM_ENV)


def test_connection_or_ip_whitelist(adapter):
    result = adapter.test_connection()
    assert result.success is True, result.message  # un 403 aici = IP-ul nu e in whitelist


def test_changed_dates(adapter):
    days, watermark = adapter.changed_dates(0)
    assert watermark >= 0
    print(f"Steam: {len(days)} zile cu date, highwatermark {watermark}")


def test_recent_sales(adapter):
    end = date.today() - timedelta(days=1)
    page = adapter.get_sales(end - timedelta(days=6), end)
    assert page.has_more is True


def test_recent_sales_sign_of_returns(adapter):
    """Verificare live a semnului retururilor (RETURN <= 0, SALE >= 0, refund >= 0)."""
    end = datetime.now()
    start = end - timedelta(days=400)
    cursor, rows = None, []
    while True:
        page = adapter.get_financial_transactions(start, end, cursor=cursor)
        rows.extend(page.items)
        if not page.has_more:
            break
        cursor = page.cursor
    returns = [t for t in rows if t.transaction_type == FinancialTransactionType.RETURN]
    for t in returns:
        print(f"Steam RETURN: {t.model_dump()}")
        assert t.net_amount <= Decimal("0")
    for t in rows:
        if t.transaction_type == FinancialTransactionType.SALE:
            assert t.net_amount >= Decimal("0")

    # Invariantul pe fiecare rand sursa, cu semne Steam: gross + returns - tax == net (in limita unui cent)
    sale_cursor = None
    while True:
        sales_page = adapter.get_sales(start.date(), end.date(), cursor=sale_cursor)
        for sale in sales_page.items:
            computed = (
                Decimal(sale.extra["gross_sales_usd"])
                + Decimal(sale.extra["gross_returns_usd"])
                - Decimal(sale.extra["net_tax_usd"])
            )
            assert abs(computed - sale.proceeds_total) <= Decimal("0.01"), (sale.external_key, sale.extra, sale.proceeds_total)
        if not sales_page.has_more:
            break
        sale_cursor = sales_page.cursor


def test_recent_refunds_are_positive(adapter):
    end = datetime.now()
    start = end - timedelta(days=400)
    cursor = None
    while True:
        page = adapter.list_refunds(start.date(), end.date(), cursor=cursor)
        assert all(r.amount >= Decimal("0") for r in page.items)
        if not page.has_more:
            break
        cursor = page.cursor


def test_public_reviews(adapter):
    app_id = STEAM_ENV["app_ids"].split(",")[0].strip()
    page = adapter.list_reviews(app_id)
    assert all(r.recommended in (True, False) for r in page.items)


def test_wishlist_stats_last_30_days(adapter):
    app_id = STEAM_ENV["app_ids"].split(",")[0].strip()
    end = date.today()
    cursor, items = None, []
    while True:
        page = adapter.get_app_stats(app_id, end - timedelta(days=30), end, cursor=cursor)
        items.extend(page.items)
        if not page.has_more:
            break
        cursor = page.cursor
    assert all(isinstance(s, AppStoreStat) and s.value >= 0 for s in items)
    adds = sum(s.value for s in items if s.metric == AppStoreStatMetric.WISHLIST_ADDS and s.country == "")
    print(f"Steam: {adds} wishlist adds in ultimele 30 de zile")
