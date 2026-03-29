"""
Cardinity unit tests — no network, pure function tests.

Tests: checkout form generation, HMAC-SHA256 signature, IPN parsing,
credential validation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, PaymentMethodType, PaymentResult, WebhookEventType
from bapp_connectors.providers.payment.cardinity.adapter import CardinityPaymentAdapter
from bapp_connectors.providers.payment.cardinity.client import (
    build_checkout_form,
    compute_signature,
)
from bapp_connectors.providers.payment.cardinity.mappers import (
    payment_result_from_cardinity,
    webhook_event_from_cardinity,
)

PROJECT_KEY = "test_project_key"
PROJECT_SECRET = "test_project_secret"


@pytest.fixture
def adapter():
    return CardinityPaymentAdapter(credentials={
        "project_key": PROJECT_KEY,
        "project_secret": PROJECT_SECRET,
    })


# ── Contract Tests ──


class TestCardinityContract:
    from tests.payment.contract import PaymentContractTests

    for _name, _method in vars(PaymentContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Signature ──


class TestSignature:

    def test_signature_is_deterministic(self):
        fields = {
            "amount": "99.99",
            "currency": "EUR",
            "order_id": "ORD-001",
            "project_id": PROJECT_KEY,
        }
        sig1 = compute_signature(fields, PROJECT_SECRET)
        sig2 = compute_signature(fields, PROJECT_SECRET)
        assert sig1 == sig2

    def test_signature_changes_with_secret(self):
        fields = {"amount": "10.00", "currency": "EUR"}
        sig1 = compute_signature(fields, "secret_a")
        sig2 = compute_signature(fields, "secret_b")
        assert sig1 != sig2

    def test_signature_changes_with_data(self):
        fields1 = {"amount": "10.00", "currency": "EUR"}
        fields2 = {"amount": "20.00", "currency": "EUR"}
        sig1 = compute_signature(fields1, PROJECT_SECRET)
        sig2 = compute_signature(fields2, PROJECT_SECRET)
        assert sig1 != sig2


# ── Checkout Form ──


class TestCheckoutForm:

    def test_form_has_required_fields(self):
        form = build_checkout_form(
            amount=99.99, currency="EUR", order_id="ORD-001",
            description="Test", project_key=PROJECT_KEY,
            project_secret=PROJECT_SECRET,
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
        )
        assert form["amount"] == "99.99"
        assert form["currency"] == "EUR"
        assert form["order_id"] == "ORD-001"
        assert form["project_id"] == PROJECT_KEY
        assert "signature" in form

    def test_form_country_defaults_to_lt(self):
        form = build_checkout_form(
            amount=50.0, currency="EUR", order_id="ORD-002",
            description="Test", project_key=PROJECT_KEY,
            project_secret=PROJECT_SECRET,
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
        )
        assert form["country"] == "LT"

    def test_form_country_override(self):
        form = build_checkout_form(
            amount=50.0, currency="EUR", order_id="ORD-003",
            description="Test", project_key=PROJECT_KEY,
            project_secret=PROJECT_SECRET,
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
            country="RO",
        )
        assert form["country"] == "RO"

    def test_form_signature_is_valid(self):
        form = build_checkout_form(
            amount=99.99, currency="EUR", order_id="ORD-004",
            description="Test", project_key=PROJECT_KEY,
            project_secret=PROJECT_SECRET,
            return_url="https://example.com/return",
            cancel_url="https://example.com/cancel",
        )
        sig = form.pop("signature")
        expected = compute_signature(form, PROJECT_SECRET)
        assert sig == expected


# ── IPN Parsing ──


class TestIPNParsing:

    def test_approved_payment(self):
        post_data = {"status": "approved", "order_id": "ORD-001", "id": "CARD-123", "amount": "99.99", "currency": "EUR"}
        result = payment_result_from_cardinity(post_data)
        assert isinstance(result, PaymentResult)
        assert result.status == "approved"
        assert result.payment_id == "CARD-123"
        assert result.method == PaymentMethodType.CARD

    def test_declined_payment(self):
        post_data = {"status": "declined", "order_id": "ORD-002", "id": "CARD-456"}
        result = payment_result_from_cardinity(post_data)
        assert result.status == "declined"

    def test_pending_payment(self):
        post_data = {"status": "pending", "order_id": "ORD-003", "id": "CARD-789"}
        result = payment_result_from_cardinity(post_data)
        assert result.status == "pending"

    def test_webhook_event_approved(self):
        post_data = {"status": "approved", "order_id": "ORD-001", "id": "CARD-123"}
        event = webhook_event_from_cardinity(post_data)
        assert event.event_type == WebhookEventType.ORDER_UPDATED
        assert event.provider == "cardinity"

    def test_webhook_event_declined(self):
        post_data = {"status": "declined", "order_id": "ORD-002", "id": "CARD-456"}
        event = webhook_event_from_cardinity(post_data)
        assert event.event_type == WebhookEventType.UNKNOWN


# ── Adapter Checkout Session ──


class TestAdapterCheckout:

    def test_creates_checkout_session(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("99.99"), currency="EUR",
            description="Test", identifier="ORD-001",
            success_url="https://example.com/ok",
            cancel_url="https://example.com/cancel",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id == "ORD-001"
        assert session.amount == Decimal("99.99")
        assert "form_data" in session.extra
        assert "signature" in session.extra["form_data"]


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def test_verify_valid_approved(self, adapter):
        from urllib.parse import urlencode
        body = urlencode({"status": "approved", "order_id": "ORD-001", "id": "C-1"}).encode()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_valid_declined(self, adapter):
        body = b'{"status": "declined", "order_id": "ORD-002"}'
        assert adapter.verify_webhook({}, body) is True

    def test_verify_invalid_status(self, adapter):
        body = b'{"status": "unknown_value"}'
        assert adapter.verify_webhook({}, body) is False

    def test_parse_webhook(self, adapter):
        body = b'{"status": "approved", "order_id": "ORD-001", "id": "C-1"}'
        event = adapter.parse_webhook({}, body)
        assert event.provider == "cardinity"
        assert event.event_id == "C-1"


# ── Credential Validation ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_project_key(self):
        adapter = CardinityPaymentAdapter(credentials={"project_secret": PROJECT_SECRET})
        assert adapter.validate_credentials() is False

    def test_missing_project_secret(self):
        adapter = CardinityPaymentAdapter(credentials={"project_key": PROJECT_KEY})
        assert adapter.validate_credentials() is False
