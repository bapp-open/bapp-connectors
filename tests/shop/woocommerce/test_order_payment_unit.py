"""Marcarea unei comenzi ca plătită în WooCommerce.

Woo are steagul lui pe comandă: el stampilează data plății și aplică efectele obișnuite. Suma
nu se trimite — Woo ia totalul comenzii și ar refuza o valoare parțială aici.
"""

from decimal import Decimal

from bapp_connectors.core.capabilities import OrderPaymentCapability
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from bapp_connectors.providers.shop.woocommerce.manifest import manifest
from tests.fake_http import FakeHttpClient

PAID = {"id": 55, "number": "55", "status": "processing", "date_paid": "2026-09-29T10:00:00"}


def _adapter(fake):
    return WooCommerceShopAdapter(credentials={"consumer_key": "k", "consumer_secret": "s"}, http_client=fake)


def _sent(fake):
    return [entry for entry in fake.calls if entry.method == "PUT"][0].kwargs["json"]


def test_declares_capability():
    assert OrderPaymentCapability in manifest.capabilities


def test_marking_paid_flips_woocommerces_own_flag():
    fake = FakeHttpClient()
    fake.add("PUT", "orders/55", PAID)
    order = _adapter(fake).mark_order_paid("55")

    assert _sent(fake) == {"set_paid": True}
    assert order.order_id == "55"


def test_the_reference_and_the_method_ride_along_when_given():
    fake = FakeHttpClient()
    fake.add("PUT", "orders/55", PAID)
    _adapter(fake).mark_order_paid("55", method="Transfer bancar", transaction_id="OP-7721",
                                   paid_at="2026-09-29T10:00:00")

    assert _sent(fake) == {
        "set_paid": True,
        "transaction_id": "OP-7721",
        "payment_method_title": "Transfer bancar",
        "date_paid": "2026-09-29T10:00:00",
    }


def test_the_amount_is_never_sent():
    """Woo ia totalul comenzii; o sumă parțială trimisă aici ar fi refuzată."""
    fake = FakeHttpClient()
    fake.add("PUT", "orders/55", PAID)
    _adapter(fake).mark_order_paid("55", amount=Decimal("119.00"))

    assert "amount" not in _sent(fake) and "total" not in _sent(fake)
