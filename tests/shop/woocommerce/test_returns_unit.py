from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.dto import ReturnKind
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from tests.fake_http import FakeHttpClient

REFUND = {"id": 91, "parent_id": 812, "date_created_gmt": "2026-09-21T10:00:00", "amount": "25.00",
          "reason": "Produs deteriorat", "line_items": [{"id": 5, "sku": "AB-1", "name": "Ciocan", "quantity": -1, "price": -25}]}
SINCE = datetime(2026, 9, 20, tzinfo=UTC)
UNTIL = datetime(2026, 9, 24, tzinfo=UTC)


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def test_declares_capability():
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest
    assert ReturnsCapability in manifest.capabilities


def test_maps_refund(adapter, fake):
    fake.add("GET", "refunds", [REFUND])
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert (r.external_id, r.external_order_id, r.kind, r.status_raw) == ("91", "812", ReturnKind.REFUND, "refunded")
    assert r.comment == "Produs deteriorat" and r.refund.amount == Decimal("25.00")
    assert (r.lines[0].sku, r.lines[0].quantity, r.lines[0].unit_price) == ("AB-1", Decimal(1), Decimal(25))
    params = fake.last_call().kwargs["params"]
    assert params["after"] == "2026-09-20T00:00:00" and params["dates_are_gmt"] == "true"


def test_drops_refunds_outside_window_when_server_ignores_dates(adapter, fake):
    fake.add("GET", "refunds", [REFUND, {**REFUND, "id": 92, "date_created_gmt": "2026-08-01T10:00:00"}])
    assert [r.external_id for r in adapter.get_returns(SINCE, UNTIL)] == ["91"]


def test_paginates(adapter, fake):
    def respond(method, path, kwargs):
        page = kwargs["params"]["page"]
        return [{**REFUND, "id": page * 1000 + i} for i in range(100 if page == 1 else 3)]
    fake.add("GET", "refunds", respond)
    assert len(adapter.get_returns(SINCE, UNTIL)) == 103


def test_future_refunds_are_skipped(adapter, fake):
    fake.add("GET", "refunds", [{**REFUND, "date_created_gmt": "2026-10-15T10:00:00"}])
    assert adapter.get_returns(SINCE, UNTIL) == []
