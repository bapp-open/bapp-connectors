from bapp_connectors.core.capabilities import OrderLookupCapability
from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter
from bapp_connectors.providers.shop.prestashop.manifest import manifest
from tests.fake_http import FakeHttpClient


def _adapter(fake):
    return PrestaShopShopAdapter(credentials={"domain": "https://shop.test", "token": "t"}, http_client=fake)


def test_declares_capability():
    assert OrderLookupCapability in manifest.capabilities


def test_finds_by_reference_uppercased():
    fake = FakeHttpClient()
    fake.add("GET", "orders", {"orders": [{"id": 7, "reference": "XKBKNABJK"}]})
    order = PrestaShopShopAdapter.find_order_by_reference(_adapter(fake), "xkbknabjk")
    assert order is not None and order.external_id == "XKBKNABJK"
    assert fake.calls[0].kwargs["params"]["filter[reference]"] == "[XKBKNABJK]"


def test_not_found_is_none():
    fake = FakeHttpClient()
    fake.add("GET", "orders", {"orders": []})
    assert _adapter(fake).find_order_by_reference("NOPE") is None


def test_digit_reference_not_found_does_not_fall_back_to_internal_id():
    fake = FakeHttpClient()
    fake.add("GET", "orders", {"orders": []})
    assert _adapter(fake).find_order_by_reference("1001") is None
    assert len(fake.calls) == 1
    assert fake.calls[0].path == "orders"
