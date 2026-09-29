"""Gomag's own order statuses: reading the shop's list and setting one by its raw name.

Gomag names its statuses in Romanian and its update endpoint takes that name, not an id, so
`RemoteOrderStatus.id` carries the name and any numeric id rides in `extra`.
"""

from bapp_connectors.core.capabilities import OrderStatusCatalogCapability
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from bapp_connectors.providers.shop.gomag.manifest import manifest
from tests.fake_http import FakeHttpClient

STATUSES = {
    "1": {"id": "1", "name": "Comanda NEW", "color": "#fff"},
    "2": {"id": "2", "name": "Livrata"},
    "9": {"id": "9", "name": "Pregatita de curier"},   # a status the merchant created
}


def _adapter(fake):
    return GomagShopAdapter(credentials={"token": "t", "shop_site": "https://s.ro"}, http_client=fake)


def test_declares_capability():
    assert OrderStatusCatalogCapability in manifest.capabilities


def test_lists_the_shops_own_statuses_custom_ones_included():
    fake = FakeHttpClient()
    fake.add("GET", "order/status/read/json", STATUSES)
    statuses = _adapter(fake).list_order_statuses()

    assert [status.id for status in statuses] == ["Comanda NEW", "Livrata", "Pregatita de curier"]
    assert statuses[0].extra["id"] == "1" and statuses[0].extra["color"] == "#fff"
    # the two Gomag knows map onto shared states; the merchant's own one does not
    assert statuses[0].framework_status == "pending"
    assert statuses[1].framework_status == "delivered"
    assert statuses[2].framework_status == ""


def test_duplicates_and_junk_rows_are_dropped():
    fake = FakeHttpClient()
    fake.add("GET", "order/status/read/json", {
        "1": {"name": "Livrata"}, "2": {"name": "Livrata"}, "3": {"name": "  "}, "4": "not a dict"})
    assert [status.id for status in _adapter(fake).list_order_statuses()] == ["Livrata"]


def test_an_empty_shop_returns_an_empty_list():
    fake = FakeHttpClient()
    fake.add("GET", "order/status/read/json", {})
    assert _adapter(fake).list_order_statuses() == []


def test_setting_a_raw_status_sends_the_name_untranslated():
    fake = FakeHttpClient()
    fake.add("GET", "order/status/json", {"success": True})
    fake.add("GET", "order/read/json", {"orders": {"55": {"id": "55", "number": "2045"}}})
    order = _adapter(fake).set_order_status_raw("55", " Pregatita de curier ")

    call = [entry for entry in fake.calls if "order/status/json" in entry.path][0]
    assert call.kwargs["params"]["status"] == "Pregatita de curier"
    assert call.kwargs["params"]["order_id"] == "55"
    assert order.order_id == "2045"


def test_an_empty_raw_status_is_refused_before_any_call():
    fake = FakeHttpClient()
    try:
        _adapter(fake).set_order_status_raw("55", "   ")
    except ValueError:
        assert fake.calls == []
    else:
        raise AssertionError("an empty status must be refused")
