from datetime import UTC, datetime

import pytest

from bapp_connectors.core.capabilities import ReturnsCapability
from bapp_connectors.core.dto import ReturnKind
from bapp_connectors.providers.shop.okazii.adapter import OkaziiShopAdapter
from tests.fake_http import FakeHttpClient


def _order(order_id, status, updated="2026-09-21T10:00:00+00:00"):
    return {"id": order_id, "createdAt": "2026-09-01T10:00:00+00:00", "updatedAt": updated,
            "bids": [{"bidId": 1, "auctionUniqueId": 9, "auctionSku": "SKU-9", "auctionTitle": "Surubelnita",
                      "amount": 2, "itemPrice": {"amount": 10, "currency": "RON"}, "status": status}]}


SINCE = datetime(2026, 9, 20, tzinfo=UTC)
UNTIL = datetime(2026, 9, 24, tzinfo=UTC)


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return OkaziiShopAdapter(credentials={"token": "t"}, http_client=fake)


def test_declares_capability():
    from bapp_connectors.providers.shop.okazii.manifest import manifest
    assert ReturnsCapability in manifest.capabilities


def test_only_returned_orders(adapter, fake):
    def respond(method, path, kwargs):
        if kwargs["params"]["page"] > 1:
            return {"hydra:member": []}
        return {"hydra:member": [_order(1, "returned"), _order(2, "delivered")]}
    fake.add("GET", "export_orders", respond)
    [r] = adapter.get_returns(SINCE, UNTIL)
    assert (r.external_id, r.external_order_id, r.kind, r.status_raw) == ("1", "1", ReturnKind.ORDER_STATUS, "returned")
    assert r.lines[0].sku == "SKU-9" and r.requested_at.tzinfo is not None
    assert fake.calls[0].kwargs["params"]["date_from"] == "2026-07-22"


def test_stops_when_server_ignores_page(adapter, fake):
    fake.add("GET", "export_orders", {"hydra:member": [_order(1, "returned")]})
    assert len(adapter.get_returns(SINCE, UNTIL)) == 1
    assert len(fake.calls) == 2


def test_old_returned_orders_are_skipped(adapter, fake):
    def respond(method, path, kwargs):
        return {"hydra:member": [_order(1, "returned", updated="2026-08-01T10:00:00+00:00")]} if kwargs["params"]["page"] == 1 else {"hydra:member": []}
    fake.add("GET", "export_orders", respond)
    assert adapter.get_returns(SINCE, UNTIL) == []


def test_future_returned_orders_are_skipped(adapter, fake):
    def respond(method, path, kwargs):
        return {"hydra:member": [_order(1, "returned", updated="2026-10-15T10:00:00+00:00")]} if kwargs["params"]["page"] == 1 else {"hydra:member": []}
    fake.add("GET", "export_orders", respond)
    assert adapter.get_returns(SINCE, UNTIL) == []
