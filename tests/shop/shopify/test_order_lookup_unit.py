from bapp_connectors.core.capabilities import OrderLookupCapability
from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
from bapp_connectors.providers.shop.shopify.manifest import manifest
from tests.fake_http import FakeHttpClient


def _adapter(fake):
    return ShopifyShopAdapter(credentials={"store_domain": "x.myshopify.com", "access_token": "t"}, http_client=fake)


def test_declares_capability():
    assert OrderLookupCapability in manifest.capabilities


def test_finds_by_name_with_hash():
    fake = FakeHttpClient()
    fake.add("GET", "orders.json", {"orders": [{"id": 450789469, "order_number": 1001, "name": "#1001",
                                                  "email": "ana@example.ro", "line_items": []}]})
    order = _adapter(fake).find_order_by_reference("1001")
    assert order is not None and order.order_id == "1001"
    params = fake.last_call().kwargs["params"]
    assert params["name"] == "#1001" and params["status"] == "any"


def test_not_found_is_none():
    fake = FakeHttpClient()
    fake.add("GET", "orders.json", {"orders": []})
    assert _adapter(fake).find_order_by_reference("#9") is None
