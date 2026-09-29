"""PrestaShop's own order states.

PrestaShop identifies a state by a numeric id and names it per language, so the id is what goes
back on a raw set and the label is the first language's name. Setting one is an order-history
row, the same call the mapped path uses.
"""

from bapp_connectors.core.capabilities import OrderStatusCatalogCapability
from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter
from bapp_connectors.providers.shop.prestashop.manifest import manifest
from tests.fake_http import FakeHttpClient

STATES = {
    "order_states": {
        "order_state": [
            {"id": "2", "name": {"language": [{"value": "Plată acceptată"}]}, "paid": "1"},
            {"id": "4", "name": {"language": [{"value": "Expediată"}]}},
            {"id": "77", "name": {"language": [{"value": "Ridicare din magazin"}]}},   # the shop's own
        ]
    }
}


def _adapter(fake):
    return PrestaShopShopAdapter(credentials={"domain": "https://s.ro", "token": "t"}, http_client=fake)


def test_declares_capability():
    assert OrderStatusCatalogCapability in manifest.capabilities


def test_lists_the_shops_states_custom_ones_included():
    fake = FakeHttpClient()
    fake.add("GET", "order_states", STATES)
    statuses = _adapter(fake).list_order_statuses()

    assert [status.id for status in statuses] == ["2", "4", "77"]
    assert [status.label for status in statuses] == ["Plată acceptată", "Expediată", "Ridicare din magazin"]
    assert statuses[0].extra == {"paid": "1"}


def test_setting_a_raw_state_writes_an_order_history_row():
    fake = FakeHttpClient()
    fake.add("POST", "order_histories", {"ok": True})
    fake.add("GET", "orders/55", {"order": {"id": "55", "reference": "ABC", "current_state": "77"}})
    _adapter(fake).set_order_status_raw("55", " 77 ")

    call = [entry for entry in fake.calls if entry.method == "POST"][0]
    assert "77" in str(call.kwargs) and "55" in str(call.kwargs)


def test_a_state_that_is_not_a_number_is_refused_before_any_call():
    fake = FakeHttpClient()
    try:
        _adapter(fake).set_order_status_raw("55", "Ridicare din magazin")
    except ValueError as exc:
        assert "numeric" in str(exc)
        assert fake.calls == []
    else:
        raise AssertionError("PrestaShop states are numeric; a name must be refused")
