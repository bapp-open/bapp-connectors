"""
MobilPay unit tests — no network, crypto roundtrip tests.

Tests: XML building, RSA+ARC4 encrypt/decrypt roundtrip, IPN parsing,
mapper functions, credential validation.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlencode

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from bapp_connectors.core.dto import CheckoutSession, PaymentMethodType, PaymentResult, WebhookEventType
from bapp_connectors.providers.payment.mobilpay.adapter import MobilPayPaymentAdapter
from bapp_connectors.providers.payment.mobilpay.client import (
    build_order_xml,
    decrypt_xml,
    encrypt_xml,
    parse_ipn_xml,
)
from bapp_connectors.providers.payment.mobilpay.mappers import (
    payment_result_from_mobilpay,
    webhook_event_from_mobilpay,
)

CLIENT_KEY = "TEST-MERCHANT-SIG"


# ── Generate test RSA keypair + self-signed cert at module level ──

def _generate_test_keypair() -> tuple[str, str]:
    """Generate a test RSA keypair and self-signed X509 certificate."""
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2024, 1, 1))
        .not_valid_after(datetime.datetime(2030, 1, 1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return private_pem, cert_pem


_TEST_PRIVATE_KEY, _TEST_PUBLIC_CERT = _generate_test_keypair()


@pytest.fixture
def adapter():
    return MobilPayPaymentAdapter(
        credentials={
            "client_key": CLIENT_KEY,
            "public_cert": _TEST_PUBLIC_CERT,
            "private_key": _TEST_PRIVATE_KEY,
        },
        config={"sandbox": True},
    )


# ── XML Building ──


class TestXMLBuilding:

    def test_builds_valid_xml(self):
        xml = build_order_xml(
            client_key=CLIENT_KEY, order_id="ORD-001",
            amount=Decimal("99.99"), currency="RON",
            description="Test Payment",
            confirm_url="https://example.com/confirm",
            return_url="https://example.com/return",
        )
        assert b"<order" in xml
        assert b'type="card"' in xml
        assert b'id="ORD-001"' in xml
        assert b"RON" in xml
        assert b"99.99" in xml
        assert CLIENT_KEY.encode() in xml

    def test_includes_contact_info(self):
        xml = build_order_xml(
            client_key=CLIENT_KEY, order_id="ORD-002",
            amount=Decimal("50.00"), currency="RON",
            description="Test",
            confirm_url="https://example.com/confirm",
            return_url="https://example.com/return",
            client_email="test@test.com",
            client_name="John Doe",
        )
        assert b"test%40test.com" in xml or b"test@test.com" in xml
        assert b"John" in xml


# ── Crypto Roundtrip ──


class TestCryptoRoundtrip:

    def test_encrypt_decrypt_roundtrip(self):
        original = b"<order><test>hello</test></order>"
        enc_data, env_key = encrypt_xml(original, _TEST_PUBLIC_CERT)
        assert enc_data != ""
        assert env_key != ""

        decrypted = decrypt_xml(enc_data, env_key, _TEST_PRIVATE_KEY)
        assert decrypted == original

    def test_full_order_roundtrip(self):
        xml = build_order_xml(
            client_key=CLIENT_KEY, order_id="ORD-RT-001",
            amount=Decimal("123.45"), currency="RON",
            description="Roundtrip Test",
            confirm_url="https://example.com/confirm",
            return_url="https://example.com/return",
        )
        enc_data, env_key = encrypt_xml(xml, _TEST_PUBLIC_CERT)
        decrypted = decrypt_xml(enc_data, env_key, _TEST_PRIVATE_KEY)
        assert b"ORD-RT-001" in decrypted
        assert b"123.45" in decrypted


# ── IPN Parsing ──


class TestIPNParsing:

    def _make_ipn_xml(self, error_code: str = "0", order_id: str = "ORD-001") -> bytes:
        return f"""<?xml version="1.0" ?>
<order type="card" id="{order_id}">
    <signature>{CLIENT_KEY}</signature>
    <invoice currency="RON" amount="99.99"/>
    <mobilpay timestamp="20240101120000" crc="abc123">
        <action>0</action>
        <error code="{error_code}">OK</error>
        <purchase>PURCH-001</purchase>
        <pan_masked>4***1234</pan_masked>
    </mobilpay>
</order>""".encode()

    def test_parses_successful_ipn(self):
        xml = self._make_ipn_xml(error_code="0")
        result = parse_ipn_xml(xml)
        assert result["order_id"] == "ORD-001"
        assert result["error_code"] == "0"
        assert result["crc"] == "abc123"
        assert result["pan_masked"] == "4***1234"

    def test_parses_failed_ipn(self):
        xml = self._make_ipn_xml(error_code="16")
        result = parse_ipn_xml(xml)
        assert result["error_code"] == "16"


# ── Mapper Tests ──


class TestMappers:

    def test_payment_result_approved(self):
        ipn_data = {"order_id": "ORD-001", "error_code": "0", "amount": "99.99", "currency": "RON"}
        result = payment_result_from_mobilpay(ipn_data)
        assert isinstance(result, PaymentResult)
        assert result.status == "approved"
        assert result.amount == Decimal("99.99")
        assert result.method == PaymentMethodType.CARD

    def test_payment_result_failed(self):
        ipn_data = {"order_id": "ORD-002", "error_code": "16", "amount": "50.00"}
        result = payment_result_from_mobilpay(ipn_data)
        assert result.status == "error_16"

    def test_webhook_event_approved(self):
        ipn_data = {"order_id": "ORD-001", "error_code": "0", "crc": "abc"}
        event = webhook_event_from_mobilpay(ipn_data)
        assert event.event_type == WebhookEventType.ORDER_UPDATED
        assert event.provider == "mobilpay"

    def test_webhook_event_failed(self):
        ipn_data = {"order_id": "ORD-002", "error_code": "16"}
        event = webhook_event_from_mobilpay(ipn_data)
        assert event.event_type == WebhookEventType.UNKNOWN


# ── Adapter Checkout ──


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
        assert "data" in session.extra["form_data"]
        assert "env_key" in session.extra["form_data"]


# ── Adapter Webhook ──


class TestAdapterWebhook:

    def _make_encrypted_ipn_body(self, error_code: str = "0") -> bytes:
        """Build an encrypted IPN body for testing."""
        ipn_xml = f"""<?xml version="1.0" ?>
<order type="card" id="ORD-IPN-001">
    <signature>{CLIENT_KEY}</signature>
    <invoice currency="RON" amount="50.00"/>
    <mobilpay timestamp="20240101120000" crc="crc123">
        <action>0</action>
        <error code="{error_code}">Test</error>
    </mobilpay>
</order>""".encode()
        enc_data, env_key = encrypt_xml(ipn_xml, _TEST_PUBLIC_CERT)
        return urlencode({"data": enc_data, "env_key": env_key}).encode()

    def test_verify_valid_ipn(self, adapter):
        body = self._make_encrypted_ipn_body()
        assert adapter.verify_webhook({}, body) is True

    def test_verify_invalid_data(self, adapter):
        body = urlencode({"data": "invalid", "env_key": "invalid"}).encode()
        assert adapter.verify_webhook({}, body) is False

    def test_verify_missing_fields(self, adapter):
        body = b"foo=bar"
        assert adapter.verify_webhook({}, body) is False

    def test_parse_webhook(self, adapter):
        body = self._make_encrypted_ipn_body(error_code="0")
        event = adapter.parse_webhook({}, body)
        assert event.provider == "mobilpay"
        assert event.event_type == WebhookEventType.ORDER_UPDATED


# ── Credential Validation ──


class TestCredentials:

    def test_valid_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_missing_client_key(self):
        adapter = MobilPayPaymentAdapter(credentials={
            "public_cert": _TEST_PUBLIC_CERT, "private_key": _TEST_PRIVATE_KEY,
        })
        assert adapter.validate_credentials() is False

    def test_missing_public_cert(self):
        adapter = MobilPayPaymentAdapter(credentials={
            "client_key": CLIENT_KEY, "private_key": _TEST_PRIVATE_KEY,
        })
        assert adapter.validate_credentials() is False

    def test_missing_private_key(self):
        adapter = MobilPayPaymentAdapter(credentials={
            "client_key": CLIENT_KEY, "public_cert": _TEST_PUBLIC_CERT,
        })
        assert adapter.validate_credentials() is False
