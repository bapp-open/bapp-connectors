"""
LibraPay unit tests — no network, pure function tests.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from bapp_connectors.core.dto import CheckoutSession, PaymentMethodType, PaymentResult, WebhookEventType
from bapp_connectors.core.errors import ValidationError
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

    def test_create_checkout_session_with_email(self, adapter):
        """The shared contract pays in EUR; LibraPay takes RON only (manual IV.1)."""
        with pytest.raises(ValidationError, match="only RON"):
            adapter.create_checkout_session(
                amount=Decimal("50.00"), currency="EUR", description="Email Test",
                identifier="TEST-002", client_email="customer@test.com",
            )
        session = adapter.create_checkout_session(
            amount=Decimal("50.00"), currency="RON", description="Email Test",
            identifier="TEST-002", client_email="customer@test.com",
        )
        assert isinstance(session, CheckoutSession)


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
        # The checkout receiver only completes on payment.completed.
        ipn = _build_signed_ipn(RC="00")
        event = webhook_event_from_librapay(ipn)
        assert event.event_type == WebhookEventType.PAYMENT_COMPLETED
        assert event.provider == "librapay"

    @pytest.mark.parametrize("action,rc", [("2", "51"), ("3", "-19"), ("3", "990")])
    def test_denied_or_errored_is_a_failed_payment(self, action, rc):
        event = webhook_event_from_librapay(_build_signed_ipn(ACTION=action, RC=rc, INT_REF=""))
        assert event.event_type == WebhookEventType.PAYMENT_FAILED

    def test_duplicate_transaction_is_not_a_second_completion(self):
        event = webhook_event_from_librapay(_build_signed_ipn(ACTION="1", RC="00"))
        assert event.event_type == WebhookEventType.UNKNOWN

    def test_sync_ping_without_desc_is_ignored(self):
        event = webhook_event_from_librapay(_build_signed_ipn(DESC=""))
        assert event.event_type == WebhookEventType.UNKNOWN

    def test_declines_do_not_collide_on_empty_int_ref(self):
        a = webhook_event_from_librapay(_build_signed_ipn(ORDER="100001", ACTION="2", RC="51", INT_REF=""))
        b = webhook_event_from_librapay(_build_signed_ipn(ORDER="100002", ACTION="2", RC="51", INT_REF=""))
        assert a.idempotency_key != b.idempotency_key


# ── Adapter Checkout ──


class TestAdapterCheckout:

    def _session(self, adapter, **kw):
        args = {"amount": Decimal("150.00"), "currency": "RON", "description": "Factura 12",
                "identifier": "checkout-" + "a" * 32}
        args.update(kw)
        return adapter.create_checkout_session(**args)

    def test_creates_session(self, adapter):
        session = self._session(adapter)
        assert isinstance(session, CheckoutSession)
        assert session.amount == Decimal("150.00")
        assert "P_SIGN" in session.extra["form_data"]

    def test_order_is_numeric_6_to_19_digits_without_leading_zero(self, adapter):
        order = self._session(adapter).session_id
        assert order.isdigit() and 6 <= len(order) <= 19 and not order.startswith("0")

    def test_orders_are_unique(self, adapter):
        assert len({self._session(adapter).session_id for _ in range(50)}) == 50

    def test_identifier_travels_in_desc_for_the_ipn(self, adapter):
        # LibraPay echoes DESC in the IPN; the checkout receiver finds checkout-<uuid> there.
        assert self._session(adapter).extra["form_data"]["DESC"] == "checkout-" + "a" * 32

    def test_desc_cut_to_50(self, adapter):
        assert len(self._session(adapter, identifier="x" * 70).extra["form_data"]["DESC"]) == 50

    def test_backref_over_80_is_refused(self, adapter):
        with pytest.raises(ValidationError, match="limit is 80"):
            self._session(adapter, success_url="https://example.com/" + "p" * 80)

    def test_max_return_url_length_is_advertised(self, adapter):
        assert adapter.max_return_url_length == 80

    def test_data_custom_carries_user_data(self, adapter):
        from bapp_connectors.core.dto import BillingDetails

        billing = BillingDetails(email="c@x.ro", phone="0722", first_name="Ion", last_name="Pop",
                                 city="Iasi", country="RO", address_line1="Str. 1", tax_id="RO123")
        form = self._session(adapter, billing=billing).extra["form_data"]
        data = json.loads(base64.b64decode(form["DATA_CUSTOM"]))
        user = data["UserData"]
        assert (user["Email"], user["Name"], user["BillingCity"], user["BillingCountry"]) == (
            "c@x.ro", "Ion Pop", "Iasi", "Romania")
        assert data["ProductsData"]["0"]["Price"] == "150.00"

    def test_ipn_is_acknowledged_with_a_plain_1(self, adapter):
        assert adapter.webhook_response("ok") == "1"
        assert adapter.webhook_response("rejected") == "1"
        assert adapter.webhook_response("error") == "0"  # withheld: LibraPay resends


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


class TestManualExample:
    """P_SIGN worked example from the LibraPay implementation manual, page 12."""

    def test_p_sign_matches_the_manual(self):
        from collections import OrderedDict

        from bapp_connectors.providers.payment.librapay.client import compute_hmac

        data = OrderedDict([
            ("AMOUNT", "11.48"), ("CURRENCY", "USD"), ("ORDER", "771446"), ("DESC", "IT Books. Qty: 2"),
            ("MERCH_NAME", "Books Online Inc."), ("MERCH_URL", "www.sample.com"),
            ("MERCHANT", "123456789012345"), ("TERMINAL", "99999999"), ("EMAIL", "pgw@mail.sample.com"),
            ("TRTYPE", "1"), ("COUNTRY", None), ("MERCH_GMT", None), ("TIMESTAMP", "20030105153021"),
            ("NONCE", "F2B2DD7E603A7ADA"), ("BACKREF", "https://www.sample.com/shop/reply"),
        ])
        key = binascii.unhexlify("00112233445566778899AABBCCDDEEFF")
        assert compute_hmac(data, key) == "FACC882CA67E109E409E3974DDEDA8AAB13A5E48"
