"""
Utrust unit tests — no network, pure function tests.

Tests: webhook HMAC verification, recursive payload sorting, IPN parsing,
credential validation.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, ConnectionTestResult, WebhookEventType
from bapp_connectors.providers.payment.utrust.adapter import UtrustPaymentAdapter
from bapp_connectors.providers.payment.utrust.client import sort_payload, verify_hmac
from bapp_connectors.providers.payment.utrust.mappers import (
    payment_result_from_webhook,
    webhook_event_from_utrust,
)

API_KEY = "test_api_key"
WEBHOOK_SECRET = "test_webhook_secret"


@pytest.fixture
def adapter():
    return UtrustPaymentAdapter(credentials={
        "api_key": API_KEY,
        "webhook_secret": WEBHOOK_SECRET,
    })


def _sign_payload(payload: dict, secret: str = WEBHOOK_SECRET) -> dict:
    """Helper: add a valid HMAC-SHA256 signature to a payload."""
    payload = dict(payload)
    sorted_data = sort_payload(payload)
    sig = hmac_mod.new(secret.encode(), sorted_data.encode(), hashlib.sha256).hexdigest()
    payload["signature"] = sig
    return payload


# ── Contract Tests ──


class TestUtrustContract:
    """Utrust checkout requires a live API — only run credential/connection contract tests."""

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True


# ── Recursive Sort ──


class TestSortPayload:

    def test_flat_payload(self):
        result = sort_payload({"b": "2", "a": "1"})
        assert result == "a1b2"

    def test_nested_payload(self):
        result = sort_payload({"resource": {"b": "2", "a": "1"}, "event_type": "test"})
        assert "event_typetest" in result
        assert "resourcea1" in result
        assert "resourceb2" in result

    def test_empty_payload(self):
        assert sort_payload({}) == ""


# ── HMAC Verification ──


class TestHMACVerification:

    def test_valid_signature(self):
        payload = _sign_payload({
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001"},
        })
        assert verify_hmac(payload, WEBHOOK_SECRET) is True

    def test_invalid_signature(self):
        payload = {
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001"},
            "signature": "invalid_sig",
        }
        assert verify_hmac(payload, WEBHOOK_SECRET) is False

    def test_missing_signature(self):
        payload = {"event_type": "ORDER.PAYMENT.RECEIVED"}
        assert verify_hmac(payload, WEBHOOK_SECRET) is False

    def test_wrong_secret(self):
        payload = _sign_payload({"event_type": "test"}, secret="correct_secret")
        assert verify_hmac(payload, "wrong_secret") is False

    def test_does_not_mutate_original(self):
        payload = _sign_payload({"event_type": "test"})
        original_keys = set(payload.keys())
        verify_hmac(payload, WEBHOOK_SECRET)
        assert set(payload.keys()) == original_keys


# ── Webhook Parsing ──


class TestWebhookParsing:

    def test_payment_received(self):
        data = {
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001", "amount": "99.99", "currency": "EUR"},
        }
        event = webhook_event_from_utrust(data)
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED
        assert event.provider == "utrust"
        assert event.event_id == "ORD-001"

    def test_payment_cancelled(self):
        data = {
            "event_type": "ORDER.PAYMENT.CANCELLED",
            "resource": {"reference": "ORD-002"},
        }
        event = webhook_event_from_utrust(data)
        assert event.event_type == WebhookEventType.PAYMENT_FAILED

    def test_unknown_event(self):
        data = {"event_type": "UNKNOWN.EVENT", "resource": {}}
        event = webhook_event_from_utrust(data)
        assert event.event_type == WebhookEventType.UNKNOWN

    def test_payment_result_from_received(self):
        data = {
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001", "amount": "99.99", "currency": "EUR"},
        }
        result = payment_result_from_webhook(data)
        assert result.status == "approved"
        assert result.payment_id == "ORD-001"
        assert result.amount == Decimal("99.99")

    def test_payment_result_from_cancelled(self):
        data = {
            "event_type": "ORDER.PAYMENT.CANCELLED",
            "resource": {"reference": "ORD-002"},
        }
        result = payment_result_from_webhook(data)
        assert result.status == "cancelled"


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def test_verify_valid_webhook(self, adapter):
        import json
        payload = _sign_payload({
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001"},
        })
        body = json.dumps(payload).encode()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_invalid_json(self, adapter):
        assert adapter.verify_webhook({}, b"not json") is False

    def test_parse_webhook(self, adapter):
        import json
        payload = {
            "event_type": "ORDER.PAYMENT.RECEIVED",
            "resource": {"reference": "ORD-001"},
        }
        body = json.dumps(payload).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "utrust"
        assert event.event_id == "ORD-001"


# ── Credential Validation ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_api_key(self):
        adapter = UtrustPaymentAdapter(credentials={"webhook_secret": WEBHOOK_SECRET})
        assert adapter.validate_credentials() is False

    def test_missing_webhook_secret(self):
        adapter = UtrustPaymentAdapter(credentials={"api_key": API_KEY})
        assert adapter.validate_credentials() is False
