"""
PayPal unit tests — no network, pure function tests.

Tests: webhook parsing, mapper functions, credential validation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto import (
    CheckoutSession,
    PaymentMethodType,
    PaymentResult,
    Refund,
    WebhookEventType,
)
from bapp_connectors.providers.payment.paypal.adapter import PayPalPaymentAdapter
from bapp_connectors.providers.payment.paypal.mappers import (
    checkout_session_from_paypal,
    payment_result_from_paypal,
    refund_from_paypal,
    webhook_event_from_paypal,
)

CLIENT_ID = "test_client_id"
APP_SECRET = "test_app_secret"


@pytest.fixture
def adapter():
    return PayPalPaymentAdapter(credentials={
        "client_id": CLIENT_ID,
        "app_secret": APP_SECRET,
    })


def _make_order_response(**overrides) -> dict:
    base = {
        "id": "PP-ORDER-123",
        "status": "CREATED",
        "purchase_units": [
            {
                "custom_id": "ORD-001",
                "amount": {"currency_code": "EUR", "value": "99.99"},
            }
        ],
        "links": [
            {"rel": "self", "href": "https://api.paypal.com/v2/checkout/orders/PP-ORDER-123"},
            {"rel": "approve", "href": "https://www.paypal.com/checkoutnow?token=PP-ORDER-123"},
        ],
    }
    base.update(overrides)
    return base


def _make_webhook_payload(event_type: str, **overrides) -> dict:
    base = {
        "id": "WH-EVT-001",
        "event_type": event_type,
        "resource": {
            "id": "PP-ORDER-123",
            "purchase_units": [
                {"custom_id": "ORD-001"},
            ],
        },
    }
    base.update(overrides)
    return base


# ── Checkout Session Mapping ──


class TestCheckoutSession:

    def test_maps_order_response(self):
        response = _make_order_response()
        session = checkout_session_from_paypal(response)
        assert isinstance(session, CheckoutSession)
        assert session.session_id == "PP-ORDER-123"
        assert session.payment_url == "https://www.paypal.com/checkoutnow?token=PP-ORDER-123"
        assert session.amount == Decimal("99.99")
        assert session.currency == "EUR"

    def test_missing_approval_url(self):
        response = _make_order_response(links=[])
        session = checkout_session_from_paypal(response)
        assert session.payment_url == ""

    def test_empty_purchase_units(self):
        response = _make_order_response(purchase_units=[])
        session = checkout_session_from_paypal(response)
        assert session.amount == Decimal("0")


# ── Payment Result Mapping ──


class TestPaymentResult:

    def test_completed_order(self):
        response = _make_order_response(status="COMPLETED")
        result = payment_result_from_paypal(response)
        assert isinstance(result, PaymentResult)
        assert result.status == "approved"
        assert result.method == PaymentMethodType.WALLET

    def test_created_order(self):
        response = _make_order_response(status="CREATED")
        result = payment_result_from_paypal(response)
        assert result.status == "pending"

    def test_voided_order(self):
        response = _make_order_response(status="VOIDED")
        result = payment_result_from_paypal(response)
        assert result.status == "cancelled"


# ── Refund Mapping ──


class TestRefund:

    def test_maps_refund_response(self):
        response = {
            "id": "REFUND-001",
            "status": "COMPLETED",
            "amount": {"value": "50.00", "currency_code": "EUR"},
        }
        result = refund_from_paypal(response, capture_id="CAP-001")
        assert isinstance(result, Refund)
        assert result.refund_id == "REFUND-001"
        assert result.payment_id == "CAP-001"
        assert result.amount == Decimal("50.00")
        assert result.currency == "EUR"


# ── Webhook Parsing ──


class TestWebhookParsing:

    def test_checkout_approved(self):
        data = _make_webhook_payload("CHECKOUT.ORDER.APPROVED")
        event = webhook_event_from_paypal(data)
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED
        assert event.provider == "paypal"

    def test_capture_completed(self):
        data = _make_webhook_payload("PAYMENT.CAPTURE.COMPLETED")
        event = webhook_event_from_paypal(data)
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED

    def test_capture_denied(self):
        data = _make_webhook_payload("PAYMENT.CAPTURE.DENIED")
        event = webhook_event_from_paypal(data)
        assert event.event_type == WebhookEventType.PAYMENT_FAILED

    def test_unknown_event(self):
        data = _make_webhook_payload("SOME.OTHER.EVENT")
        event = webhook_event_from_paypal(data)
        assert event.event_type == WebhookEventType.UNKNOWN

    def test_extracts_custom_id(self):
        data = _make_webhook_payload("CHECKOUT.ORDER.APPROVED")
        event = webhook_event_from_paypal(data)
        assert event.extra["custom_id"] == "ORD-001"


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def test_verify_valid_event(self, adapter):
        import json
        body = json.dumps(_make_webhook_payload("CHECKOUT.ORDER.APPROVED")).encode()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_unknown_event(self, adapter):
        import json
        body = json.dumps({"event_type": "UNKNOWN"}).encode()
        assert adapter.verify_webhook({}, body) is False

    def test_verify_invalid_json(self, adapter):
        assert adapter.verify_webhook({}, b"not json") is False

    def test_parse_webhook(self, adapter):
        import json
        body = json.dumps(_make_webhook_payload("PAYMENT.CAPTURE.COMPLETED")).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "paypal"
        assert event.event_id == "WH-EVT-001"


# ── Credential Validation ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_client_id(self):
        adapter = PayPalPaymentAdapter(credentials={"app_secret": APP_SECRET})
        assert adapter.validate_credentials() is False

    def test_missing_app_secret(self):
        adapter = PayPalPaymentAdapter(credentials={"client_id": CLIENT_ID})
        assert adapter.validate_credentials() is False
