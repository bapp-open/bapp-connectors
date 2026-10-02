"""Integrare Google Play pe contul real (cere BAPP_GOOGLE_PLAY_*). Nu scrie nimic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from bapp_connectors.core.registry import registry
from tests.appstore.conftest import GOOGLE_ENV, skip_unless_google

pytestmark = [pytest.mark.integration, skip_unless_google]


@pytest.fixture(scope="module")
def adapter():
    import bapp_connectors.providers.appstore.google_play  # noqa: F401

    return registry.create_adapter("appstore", "google_play", credentials=GOOGLE_ENV)


def test_connection(adapter):
    assert adapter.test_connection().success is True


def test_previous_month_earnings_net(adapter):
    first_of_month = date.today().replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    page = adapter.get_financial_transactions(
        datetime.combine(last_month.replace(day=1), datetime.min.time()),
        datetime.combine(last_month, datetime.max.time()),
    )
    net = sum((t.net_amount for t in page.items), Decimal("0"))
    print(f"Google Play earnings {last_month:%Y%m}: net {net} ({len(page.items)} randuri)")
    assert all(t.payout_id == f"{last_month:%Y%m}:{t.currency}" for t in page.items)
    # Antetul CSV-ului de earnings trebuie sa aiba coloana de pachet (verificare pe headerele reale)
    assert all(t.extra.get("package_id") for t in page.items), [t.extra for t in page.items[:3]]


def test_previous_month_sales(adapter):
    first_of_month = date.today().replace(day=1)
    last_month = first_of_month - timedelta(days=1)
    page = adapter.get_sales(last_month.replace(day=1), last_month)
    if page.items:
        print(sorted(page.items[0].provider_meta.raw_payload.keys()))
    assert all(s.external_key for s in page.items)
    # Coloanele reale ale raportului de vanzari trebuie sa umple pachetul si SKU-ul
    assert all(s.app_id for s in page.items), [s.provider_meta.raw_payload for s in page.items[:3]]
    assert all(s.sku for s in page.items), [s.provider_meta.raw_payload for s in page.items[:3]]


def test_reviews_merge(adapter):
    package = GOOGLE_ENV["package_names"].split(",")[0].strip()
    if not package:
        pytest.skip("BAPP_GOOGLE_PLAY_PACKAGE lipseste")
    page = adapter.list_reviews(package, since=datetime.now() - timedelta(days=60))
    assert all(r.review_id for r in page.items)
