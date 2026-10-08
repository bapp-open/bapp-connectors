"""
WebhookEvent.payment: set by every payment provider only when the message confirms
the money was taken, with the merchant reference, the amount and an uppercase currency.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.providers.payment.cardinity.mappers import webhook_event_from_cardinity
from bapp_connectors.providers.payment.euplatesc.mappers import webhook_event_from_euplatesc
from bapp_connectors.providers.payment.librapay.mappers import webhook_event_from_librapay
from bapp_connectors.providers.payment.mobilpay.client import parse_ipn_xml
from bapp_connectors.providers.payment.mobilpay.mappers import webhook_event_from_mobilpay
from bapp_connectors.providers.payment.netopia.mappers import webhook_event_from_netopia
from bapp_connectors.providers.payment.paypal.mappers import webhook_event_from_paypal
from bapp_connectors.providers.payment.stripe.mappers import webhook_event_from_stripe
from bapp_connectors.providers.payment.utrust.mappers import webhook_event_from_utrust

REF = "o-0123456789abcdef0123456789abcdef"


def netopia(status=3):
    return webhook_event_from_netopia(
        {"order": {"orderID": REF}, "payment": {"ntpID": "NTP1", "status": status, "amount": 120.5, "currency": "RON"}}
    )


def librapay(**over):
    data = {
        "ACTION": "0",
        "RC": "00",
        "ORDER": "6123456",
        "DESC": REF,
        "AMOUNT": "120.50",
        "CURRENCY": "ron",
        "INT_REF": "IR1",
        "TRTYPE": "0",
    }
    return webhook_event_from_librapay({**data, **over})


def euplatesc(**over):
    data = {"action": "0", "ep_id": "EP1", "invoice_id": REF, "amount": "120.50", "curr": "RON", "sec_status": "9"}
    return webhook_event_from_euplatesc({**data, **over})


def cardinity(status="approved"):
    return webhook_event_from_cardinity(
        {"id": "C1", "order_id": REF, "status": status, "amount": "120.50", "currency": "EUR"}
    )


def mobilpay(action="confirmed", error_code="0"):
    return webhook_event_from_mobilpay(
        {
            "order_id": REF,
            "error_code": error_code,
            "action": action,
            "crc": "x",
            "processed_amount": "120.50",
            "currency": "RON",
        }
    )


def utrust(event_type="ORDER.PAYMENT.RECEIVED"):
    return webhook_event_from_utrust(
        {"event_type": event_type, "resource": {"reference": REF, "amount": "120.50", "currency": "eur"}}
    )


def paypal(event_type="PAYMENT.CAPTURE.COMPLETED"):
    return webhook_event_from_paypal(
        {
            "id": "WH1",
            "event_type": event_type,
            "resource": {"id": "CAP1", "custom_id": REF, "amount": {"value": "120.50", "currency_code": "EUR"}},
        }
    )


def stripe(raw_type="checkout.session.completed", payment_status="paid"):
    return webhook_event_from_stripe(
        {
            "id": "evt_1",
            "type": raw_type,
            "data": {
                "object": {
                    "id": "cs_1",
                    "payment_intent": "pi_1",
                    "payment_status": payment_status,
                    "amount_total": 12050,
                    "currency": "eur",
                    "metadata": {"identifier": REF},
                }
            },
        }
    )


CONFIRMED = [
    (netopia, "RON"),
    (librapay, "RON"),
    (euplatesc, "RON"),
    (cardinity, "EUR"),
    (mobilpay, "RON"),
    (utrust, "EUR"),
    (paypal, "EUR"),
    (stripe, "EUR"),
]


@pytest.mark.parametrize(("build", "currency"), CONFIRMED, ids=[b.__name__ for b, _ in CONFIRMED])
def test_confirmed_sale_carries_reference_amount_and_currency(build, currency):
    payment = build().payment
    assert payment is not None
    assert payment.reference == REF
    assert payment.amount == Decimal("120.50")
    assert payment.currency == currency
    assert payment.provider_meta is None  # the raw payload already sits on the event


NOT_CONFIRMED = {
    "netopia_opened": lambda: netopia(status=2),
    "netopia_refunded": lambda: netopia(status=6),
    "librapay_refund": lambda: librapay(TRTYPE="24"),
    "librapay_declined": lambda: librapay(ACTION="2", RC="51"),
    "librapay_sync_ping": lambda: librapay(DESC=""),
    "euplatesc_suspect": lambda: euplatesc(sec_status="5"),
    "euplatesc_failed": lambda: euplatesc(action="1"),
    "cardinity_pending": lambda: cardinity(status="pending"),
    "cardinity_declined": lambda: cardinity(status="declined"),
    "mobilpay_paid_pending": lambda: mobilpay(action="paid_pending"),
    "mobilpay_canceled": lambda: mobilpay(action="canceled"),
    "mobilpay_credit": lambda: mobilpay(action="credit"),
    "mobilpay_error": lambda: mobilpay(error_code="16"),
    "utrust_cancelled": lambda: utrust(event_type="ORDER.PAYMENT.CANCELLED"),
    "paypal_order_approved": lambda: paypal(event_type="CHECKOUT.ORDER.APPROVED"),
    "paypal_capture_denied": lambda: paypal(event_type="PAYMENT.CAPTURE.DENIED"),
    "stripe_session_unpaid": lambda: stripe(payment_status="unpaid"),
    "stripe_payment_intent": lambda: stripe(raw_type="payment_intent.succeeded"),
}


@pytest.mark.parametrize("build", NOT_CONFIRMED.values(), ids=NOT_CONFIRMED.keys())
def test_no_payment_unless_the_money_was_taken(build):
    assert build().payment is None


def test_event_types_are_unchanged():
    """The payment field is additive: these providers keep their event types."""
    assert euplatesc().event_type == "order.updated"
    assert cardinity().event_type == "order.updated"
    assert mobilpay().event_type == "order.updated"


def test_mobilpay_ipn_reads_the_invoice_currency():
    xml = f"""<?xml version="1.0" ?>
<order type="card" id="{REF}">
    <invoice currency="EUR" amount="120.50"/>
    <mobilpay timestamp="20240101120000" crc="abc">
        <action>confirmed</action>
        <error code="0">OK</error>
        <processed_amount>120.50</processed_amount>
    </mobilpay>
</order>""".encode()
    ipn = parse_ipn_xml(xml)
    assert ipn["currency"] == "EUR"
    assert ipn["invoice_amount"] == "120.50"
    payment = webhook_event_from_mobilpay(ipn).payment
    assert (payment.reference, payment.amount, payment.currency) == (REF, Decimal("120.50"), "EUR")


def test_payment_survives_json_dump():
    """The Django side forwards model_dump(mode="json") into flows: Decimal must serialize."""
    dumped = netopia().model_dump(mode="json")
    assert Decimal(dumped["payment"]["amount"]) == Decimal("120.50")
    assert dumped["payment"]["reference"] == REF
