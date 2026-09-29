"""WooCommerce's own order statuses.

WooCommerce has no endpoint that lists statuses; the orders-totals report is the documented way
and it includes whatever a plugin or the merchant registered. Setting one is a plain order
update with the slug, so a custom status needs no translation.
"""

from bapp_connectors.core.capabilities import OrderStatusCatalogCapability
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from bapp_connectors.providers.shop.woocommerce.manifest import manifest
from tests.fake_http import FakeHttpClient

TOTALS = [
    {"slug": "pending", "name": "Pending payment", "total": "3"},
    {"slug": "processing", "name": "Processing", "total": "7"},
    {"slug": "awaiting-courier", "name": "Așteaptă curierul", "total": "1"},   # registered by the shop
]


def _adapter(fake):
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def test_declares_capability():
    assert OrderStatusCatalogCapability in manifest.capabilities


def test_lists_the_shops_statuses_custom_ones_included():
    fake = FakeHttpClient()
    fake.add("GET", "reports/orders/totals", TOTALS)
    statuses = _adapter(fake).list_order_statuses()

    assert [status.id for status in statuses] == ["pending", "processing", "awaiting-courier"]
    assert statuses[2].label == "Așteaptă curierul"
    assert statuses[0].framework_status == "pending"
    assert statuses[2].framework_status == ""      # the shop's own one maps to nothing shared
    assert statuses[1].extra == {"total": "7"}


def test_junk_rows_and_duplicates_are_dropped():
    fake = FakeHttpClient()
    fake.add("GET", "reports/orders/totals", [
        {"slug": "processing"}, {"slug": "processing"}, {"slug": ""}, "not a dict"])
    assert [status.id for status in _adapter(fake).list_order_statuses()] == ["processing"]


def test_setting_a_raw_slug_goes_straight_onto_the_order():
    fake = FakeHttpClient()
    fake.add("PUT", "orders/55", {"id": 55, "number": "55", "status": "awaiting-courier"})
    order = _adapter(fake).set_order_status_raw("55", " awaiting-courier ")

    call = [entry for entry in fake.calls if entry.method == "PUT"][0]
    assert call.kwargs["json"] == {"status": "awaiting-courier"}
    assert order.order_id == "55"


def test_an_empty_slug_is_refused_before_any_call():
    fake = FakeHttpClient()
    try:
        _adapter(fake).set_order_status_raw("55", "  ")
    except ValueError:
        assert fake.calls == []
    else:
        raise AssertionError("an empty slug must be refused")
