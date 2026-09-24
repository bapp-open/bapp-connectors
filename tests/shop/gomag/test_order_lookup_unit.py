from bapp_connectors.core.capabilities import OrderLookupCapability
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from bapp_connectors.providers.shop.gomag.manifest import manifest
from tests.fake_http import FakeHttpClient


def _adapter(fake):
    return GomagShopAdapter(credentials={"token": "t", "shop_site": "https://s.ro"}, http_client=fake)


def test_declares_capability():
    assert OrderLookupCapability in manifest.capabilities


def test_finds_by_number():
    fake = FakeHttpClient()
    fake.add("GET", "order/read/json", {"orders": {"55": {"id": "55", "number": "2045", "email": "a@b.ro"}}})
    order = _adapter(fake).find_order_by_reference("2045")
    assert order is not None and order.order_id == "2045"


def test_empty_response_is_none():
    fake = FakeHttpClient()
    fake.add("GET", "order/read/json", {"orders": []})
    assert _adapter(fake).find_order_by_reference("2045") is None
