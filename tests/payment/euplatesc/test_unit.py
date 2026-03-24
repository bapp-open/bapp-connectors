"""
EuPlatesc unit tests — no network, pure function tests.

Tests: checkout form generation, HMAC-MD5 signature roundtrip, IPN verification,
IPN parsing, invalid signature rejection, credential validation.
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
from collections import OrderedDict
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, PaymentMethodType, PaymentResult, WebhookEventType
from bapp_connectors.providers.payment.euplatesc.adapter import EuPlatescPaymentAdapter
from bapp_connectors.providers.payment.euplatesc.client import (
    _enc,
    build_checkout_form,
    compute_hmac,
    verify_ipn_hmac,
)
from bapp_connectors.providers.payment.euplatesc.mappers import (
    payment_result_from_ipn,
    webhook_event_from_euplatesc,
)

MERCHANT_ID = "testmerchant"
MERCHANT_KEY_HEX = "00112233445566778899aabbccddeeff"
MERCHANT_KEY = binascii.unhexlify(MERCHANT_KEY_HEX)


@pytest.fixture
def adapter():
    return EuPlatescPaymentAdapter(credentials={
        "merchant_id": MERCHANT_ID,
        "merchant_key": MERCHANT_KEY_HEX,
    })


def _build_signed_ipn(**overrides) -> dict:
    """Helper to build a valid IPN dict with correct fp_hash."""
    ipn = {
        "amount": "99.99", "curr": "RON", "invoice_id": "ORD-001",
        "ep_id": "EP123", "merch_id": MERCHANT_ID, "action": "0",
        "message": "Approved", "approval": "ABC123",
        "timestamp": "20240101120000", "nonce": "abc123",
    }
    ipn.update(overrides)

    fields = ["amount", "curr", "invoice_id", "ep_id", "merch_id", "action", "message", "approval", "timestamp", "nonce"]
    hash_str = ""
    for f in fields:
        hash_str += _enc(ipn[f])
    if "sec_status" in ipn:
        hash_str += _enc(ipn["sec_status"])
    ipn["fp_hash"] = hmac.new(MERCHANT_KEY, hash_str.encode(), hashlib.md5).hexdigest().upper()
    return ipn


# ── Contract Tests ──


class TestEuPlatescContract:
    from tests.payment.contract import PaymentContractTests

    for _name, _method in vars(PaymentContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Encoding ──


class TestEncoding:

    def test_enc_string(self):
        assert _enc("test") == "4test"

    def test_enc_number(self):
        assert _enc(99.99) == "599.99"

    def test_enc_empty(self):
        assert _enc("") == "0"

    def test_enc_unicode(self):
        result = _enc("ă")
        assert result == f"{len('ă'.encode())}ă"


# ── Checkout Form ──


class TestCheckoutForm:

    def test_form_has_required_fields(self):
        form = build_checkout_form(
            amount=99.99, currency="RON", invoice_id="ORD-001",
            description="Test", merchant_id=MERCHANT_ID, merchant_key=MERCHANT_KEY,
        )
        assert form["amount"] == "99.99"
        assert form["curr"] == "RON"
        assert form["invoice_id"] == "ORD-001"
        assert form["merch_id"] == MERCHANT_ID
        assert "fp_hash" in form
        assert "timestamp" in form
        assert "nonce" in form

    def test_form_includes_back_url(self):
        form = build_checkout_form(
            amount=50.0, currency="EUR", invoice_id="ORD-002",
            description="Test", merchant_id=MERCHANT_ID, merchant_key=MERCHANT_KEY,
            back_url="https://myshop.com/thanks",
        )
        assert form["backurl"] == "https://myshop.com/thanks"

    def test_form_includes_client_data(self):
        form = build_checkout_form(
            amount=50.0, currency="RON", invoice_id="ORD-003",
            description="Test", merchant_id=MERCHANT_ID, merchant_key=MERCHANT_KEY,
            client_data={"email": "test@test.com", "fname": "John"},
        )
        assert form["email"] == "test@test.com"
        assert form["fname"] == "John"

    def test_form_hmac_is_valid(self):
        form = build_checkout_form(
            amount=99.99, currency="RON", invoice_id="ORD-004",
            description="Test", merchant_id=MERCHANT_ID, merchant_key=MERCHANT_KEY,
        )
        # Recompute and verify
        data = OrderedDict([
            ("amount", form["amount"]), ("curr", form["curr"]),
            ("invoice_id", form["invoice_id"]), ("order_desc", form["order_desc"]),
            ("merch_id", form["merch_id"]), ("timestamp", form["timestamp"]),
            ("nonce", form["nonce"]),
        ])
        expected = compute_hmac(data, MERCHANT_KEY)
        assert form["fp_hash"] == expected


# ── IPN Verification ──


class TestIPNVerification:

    def test_valid_ipn_passes(self):
        ipn = _build_signed_ipn()
        assert verify_ipn_hmac(ipn, MERCHANT_KEY) is True

    def test_invalid_hash_fails(self):
        ipn = _build_signed_ipn()
        ipn["fp_hash"] = "INVALID_HASH"
        assert verify_ipn_hmac(ipn, MERCHANT_KEY) is False

    def test_tampered_amount_fails(self):
        ipn = _build_signed_ipn()
        ipn["amount"] = "999.99"  # tampered
        assert verify_ipn_hmac(ipn, MERCHANT_KEY) is False

    def test_missing_hash_fails(self):
        ipn = _build_signed_ipn()
        del ipn["fp_hash"]
        assert verify_ipn_hmac(ipn, MERCHANT_KEY) is False

    def test_ipn_with_sec_status(self):
        ipn = _build_signed_ipn(sec_status="9")
        assert verify_ipn_hmac(ipn, MERCHANT_KEY) is True

    def test_wrong_key_fails(self):
        ipn = _build_signed_ipn()
        wrong_key = binascii.unhexlify("ffeeddccbbaa99887766554433221100")
        assert verify_ipn_hmac(ipn, wrong_key) is False


# ── IPN Parsing ──


class TestIPNParsing:

    def test_approved_payment(self):
        ipn = _build_signed_ipn(action="0")
        result = payment_result_from_ipn(ipn)
        assert isinstance(result, PaymentResult)
        assert result.status == "approved"
        assert result.payment_id == "EP123"
        assert result.amount == Decimal("99.99")
        assert result.currency == "RON"
        assert result.method == PaymentMethodType.CARD

    def test_failed_payment(self):
        ipn = _build_signed_ipn(action="2")
        result = payment_result_from_ipn(ipn)
        assert result.status == "error_2"

    def test_suspect_payment(self):
        ipn = _build_signed_ipn(action="0", sec_status="5")
        result = payment_result_from_ipn(ipn)
        assert result.status == "suspect"

    def test_approved_with_good_sec_status(self):
        ipn = _build_signed_ipn(action="0", sec_status="9")
        result = payment_result_from_ipn(ipn)
        assert result.status == "approved"

    def test_webhook_event_mapping(self):
        ipn = _build_signed_ipn(action="0")
        event = webhook_event_from_euplatesc(ipn)
        assert event.event_type == WebhookEventType.ORDER_UPDATED
        assert event.provider == "euplatesc"

    def test_webhook_event_failed(self):
        ipn = _build_signed_ipn(action="1")
        event = webhook_event_from_euplatesc(ipn)
        assert event.event_type == WebhookEventType.UNKNOWN


# ── Adapter Checkout Session ──


class TestAdapterCheckout:

    def test_creates_checkout_session(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("99.99"), currency="RON",
            description="Test", identifier="ORD-001",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id == "ORD-001"
        assert session.amount == Decimal("99.99")
        assert "form_data" in session.extra
        assert "fp_hash" in session.extra["form_data"]

    def test_checkout_includes_email(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("50.00"), currency="EUR",
            description="Test", identifier="ORD-002",
            client_email="test@test.com",
        )
        assert session.extra["form_data"].get("email") == "test@test.com"


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def test_verify_valid_ipn(self, adapter):
        ipn = _build_signed_ipn()
        from urllib.parse import urlencode
        body = urlencode(ipn).encode()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_invalid_ipn(self, adapter):
        body = b"amount=99.99&curr=RON&fp_hash=INVALID"
        assert adapter.verify_webhook({}, body) is False

    def test_parse_ipn(self, adapter):
        ipn = _build_signed_ipn()
        from urllib.parse import urlencode
        body = urlencode(ipn).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "euplatesc"
        assert event.event_id == "EP123"


# ── Credential Validation ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_merchant_id(self):
        adapter = EuPlatescPaymentAdapter(credentials={"merchant_key": MERCHANT_KEY_HEX})
        assert adapter.validate_credentials() is False

    def test_missing_merchant_key(self):
        adapter = EuPlatescPaymentAdapter(credentials={"merchant_id": MERCHANT_ID})
        assert adapter.validate_credentials() is False

    def test_invalid_hex_key(self):
        adapter = EuPlatescPaymentAdapter(credentials={
            "merchant_id": MERCHANT_ID,
            "merchant_key": "not_hex",
        })
        assert adapter.validate_credentials() is False
