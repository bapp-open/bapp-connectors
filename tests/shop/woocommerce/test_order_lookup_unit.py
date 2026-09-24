import pytest

from bapp_connectors.core.capabilities import OrderLookupCapability
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from tests.fake_http import FakeHttpClient

ORDER = {
    "id": 812, "number": "1001", "status": "completed", "currency": "RON",
    "billing": {"email": "Ana@Example.ro", "phone": "0722", "first_name": "Ana", "last_name": "P"},
    "line_items": [{"id": 1, "product_id": 5, "sku": "AB-1", "name": "Ciocan", "quantity": 2, "price": "10"}],
    "date_created": "2026-09-01T10:00:00", "date_completed": "2026-09-03T12:00:00",
}


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def test_declares_capability():
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest
    assert OrderLookupCapability in manifest.capabilities


def test_finds_by_display_number(adapter, fake):
    fake.add("GET", "orders", [ORDER])
    order = adapter.find_order_by_reference("1001")
    assert order is not None and order.order_id == "1001" and order.external_id == "812"
    assert fake.last_call().kwargs["params"]["search"] == "1001"


def test_search_hit_with_other_number_is_ignored(adapter, fake):
    fake.add("GET", "orders", [{**ORDER, "number": "10011"}])
    assert adapter.find_order_by_reference("1001") is None


def test_empty_reference_short_circuits(adapter, fake):
    assert adapter.find_order_by_reference("  ") is None
    assert fake.calls == []
