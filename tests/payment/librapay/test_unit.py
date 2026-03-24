"""
LibraPay unit tests — no network, pure function tests.
"""

from __future__ import annotations

import binascii
import hashlib
import hmac
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, PaymentMethodType, PaymentResult, WebhookEventType
from bapp_connectors.providers.payment.librapay.adapter import LibraPayPaymentAdapter
from bapp_connectors.providers.payment.librapay.client import _enc, build_checkout_form, verify_ipn_hmac
from bapp_connectors.providers.payment.librapay.mappers import payment_result_from_ipn, webhook_event_from_librapay

MERCHANT = "TESTMERCH"
TERMINAL = "TESTTERM"
KEY_HEX = "00112233445566778899aabbccddeeff"
KEY = binascii.unhexlify(KEY_HEX)


@pytest.fixture
def adapter():
    return LibraPayPaymentAdapter(credentials={
        "merchant": MERCHANT,
        "terminal": TERMINAL,
        "key": KEY_HEX,
        "merchant_name": "Test Shop",
        "merchant_url": "https://test.com",
        "merchant_email": "test@test.com",
    })


def _build_signed_ipn(**overrides) -> dict:
    """Build a valid IPN with correct P_SIGN."""
    ipn = {
        "TERMINAL": TERMINAL, "TRTYPE": "0", "ORDER": "100001",
        "AMOUNT": "150.00", "CURRENCY": "RON", "DESC": "Order.1",
        "ACTION": "0", "RC": "00", "MESSAGE": "Approved",
        "RRN": "R123", "INT_REF": "IR456", "APPROVAL": "APP789",
        "TIMESTAMP": "20240101120000", "NONCE": "abc123",
    }
    ipn.update(overrides)

    fields = ["TERMINAL", "TRTYPE", "ORDER", "AMOUNT", "CURRENCY", "DESC",
              "ACTION", "RC", "MESSAGE", "RRN", "INT_REF", "APPROVAL", "TIMESTAMP", "NONCE"]
    hash_str = ""
    for f in fields:
        hash_str += _enc(ipn.get(f, ""))
    ipn["P_SIGN"] = hmac.new(KEY, hash_str.encode(), hashlib.sha1).hexdigest().upper()
    return ipn


# ── Contract Tests ──


class TestLibraPayContract:
    from tests.payment.contract import PaymentContractTests

    for _name, _method in vars(PaymentContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


# ── Encoding ──


class TestEncoding:

    def test_enc_string(self):
        assert _enc("test") == "4test"

    def test_enc_none(self):
        assert _enc(None) == "-"

    def test_enc_number(self):
        assert _enc(150.00) == "5150.0"


# ── Checkout Form ──


class TestCheckoutForm:

    def test_form_has_required_fields(self):
        form = build_checkout_form(
            amount=150.0, currency="RON", order_id="100001",
            description="Test", merchant=MERCHANT, terminal=TERMINAL,
            merchant_name="Test", merchant_url="https://t.com",
            merchant_email="t@t.com", key=KEY,
        )
        assert form["AMOUNT"] == "150.00"
        assert form["CURRENCY"] == "RON"
        assert form["ORDER"] == "100001"
        assert form["TERMINAL"] == TERMINAL
        assert "P_SIGN" in form
        assert "TIMESTAMP" in form
        assert "NONCE" in form

    def test_form_includes_back_url(self):
        form = build_checkout_form(
            amount=50.0, currency="RON", order_id="100002",
            description="Test", merchant=MERCHANT, terminal=TERMINAL,
            merchant_name="Test", merchant_url="https://t.com",
            merchant_email="t@t.com", key=KEY,
            back_url="https://myshop.com/thanks",
        )
        assert form["BACKREF"] == "https://myshop.com/thanks"


# ── IPN Verification ──


class TestIPNVerification:

    def test_valid_ipn_passes(self):
        ipn = _build_signed_ipn()
        assert verify_ipn_hmac(ipn, KEY) is True

    def test_invalid_hash_fails(self):
        ipn = _build_signed_ipn()
        ipn["P_SIGN"] = "INVALID"
        assert verify_ipn_hmac(ipn, KEY) is False

    def test_tampered_amount_fails(self):
        ipn = _build_signed_ipn()
        ipn["AMOUNT"] = "999.99"
        assert verify_ipn_hmac(ipn, KEY) is False

    def test_wrong_key_fails(self):
        ipn = _build_signed_ipn()
        wrong_key = binascii.unhexlify("ffeeddccbbaa99887766554433221100")
        assert verify_ipn_hmac(ipn, wrong_key) is False


# ── IPN Parsing ──


class TestIPNParsing:

    def test_approved_payment(self):
        ipn = _build_signed_ipn(RC="00")
        result = payment_result_from_ipn(ipn)
        assert isinstance(result, PaymentResult)
        assert result.status == "approved"
        assert result.payment_id == "IR456"
        assert result.amount == Decimal("150.00")
        assert result.currency == "RON"
        assert result.method == PaymentMethodType.CARD
        assert result.extra["rc"] == "00"

    def test_failed_payment(self):
        ipn = _build_signed_ipn(RC="51")
        result = payment_result_from_ipn(ipn)
        assert result.status == "error_51"

    def test_webhook_event_approved(self):
        ipn = _build_signed_ipn(RC="00")
        event = webhook_event_from_librapay(ipn)
        assert event.event_type == WebhookEventType.ORDER_UPDATED
        assert event.provider == "librapay"

    def test_webhook_event_failed(self):
        ipn = _build_signed_ipn(RC="51")
        event = webhook_event_from_librapay(ipn)
        assert event.event_type == WebhookEventType.UNKNOWN


# ── Adapter Checkout ──


class TestAdapterCheckout:

    def test_creates_session(self, adapter):
        session = adapter.create_checkout_session(
            amount=Decimal("150.00"), currency="RON",
            description="Test", identifier="100001",
        )
        assert isinstance(session, CheckoutSession)
        assert session.session_id == "100001"
        assert session.amount == Decimal("150.00")
        assert "P_SIGN" in session.extra["form_data"]


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def test_verify_valid_ipn(self, adapter):
        ipn = _build_signed_ipn()
        from urllib.parse import urlencode
        body = urlencode(ipn).encode()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_invalid_ipn(self, adapter):
        body = b"AMOUNT=150&CURRENCY=RON&P_SIGN=INVALID"
        assert adapter.verify_webhook({}, body) is False

    def test_parse_ipn(self, adapter):
        ipn = _build_signed_ipn()
        from urllib.parse import urlencode
        body = urlencode(ipn).encode()
        event = adapter.parse_webhook({}, body)
        assert event.provider == "librapay"


# ── Credentials ──


class TestCredentials:

    def test_valid(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_merchant(self):
        a = LibraPayPaymentAdapter(credentials={"terminal": "T", "key": KEY_HEX})
        assert a.validate_credentials() is False

    def test_missing_key(self):
        a = LibraPayPaymentAdapter(credentials={"merchant": "M", "terminal": "T"})
        assert a.validate_credentials() is False

    def test_invalid_hex_key(self):
        a = LibraPayPaymentAdapter(credentials={"merchant": "M", "terminal": "T", "key": "not_hex"})
        assert a.validate_credentials() is False
