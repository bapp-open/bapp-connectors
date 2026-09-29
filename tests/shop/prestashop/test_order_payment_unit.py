"""Marcarea unei comenzi ca plătită în PrestaShop.

PrestaShop n-are steag de plată pe comandă: plata se exprimă prin starea în care stă. Starea se
caută în magazin (prima cu marcajul `paid`), ca un comerciant care și-a făcut propria stare de
plată să fie respectat, și se poate fixa din configurarea conexiunii.
"""

from bapp_connectors.core.capabilities import OrderPaymentCapability
from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter
from bapp_connectors.providers.shop.prestashop.manifest import manifest
from tests.fake_http import FakeHttpClient

ORDER = {"order": {"id": "55", "reference": "ABC", "current_state": "2"}}
STATES = {
    "order_states": {
        "order_state": [
            {"id": "1", "name": {"language": [{"value": "Așteaptă plata"}]}, "paid": "0"},
            {"id": "11", "name": {"language": [{"value": "Încasat prin OP"}]}, "paid": "1"},
        ]
    }
}


def _adapter(fake, **config):
    return PrestaShopShopAdapter(credentials={"domain": "https://s.ro", "token": "t"},
                                 http_client=fake, config=config or None)


def _history(fake):
    return [entry for entry in fake.calls if entry.method == "POST"][0]


def test_declares_capability():
    assert OrderPaymentCapability in manifest.capabilities


def test_the_paid_state_is_read_from_the_shop_custom_ones_included():
    fake = FakeHttpClient()
    fake.add("GET", "order_states", STATES)
    assert _adapter(fake).paid_state_id() == "11"


def test_the_connection_can_pin_the_state():
    fake = FakeHttpClient()
    fake.add("GET", "order_states", STATES)
    assert _adapter(fake, paid_state_id="4").paid_state_id() == "4"
    assert fake.calls == []                      # nu mai întreabă magazinul


def test_a_shop_that_will_not_answer_falls_back_to_the_default_state():
    fake = FakeHttpClient()   # fără regulă pentru order_states
    assert _adapter(fake).paid_state_id() == PrestaShopShopAdapter.DEFAULT_PAID_STATE


def test_marking_paid_writes_an_order_history_row_with_that_state():
    fake = FakeHttpClient()
    fake.add("GET", "order_states", STATES)
    fake.add("POST", "order_histories", {"ok": True})
    fake.add("GET", "orders/55", ORDER)
    order = _adapter(fake).mark_order_paid("55")

    body = str(_history(fake).kwargs)
    assert "11" in body and "55" in body
    assert order.order_id == "55"
