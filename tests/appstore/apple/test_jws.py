"""Verificarea JWS (x5c) pentru App Store Server Notifications V2 si decodarea payload-ului."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from bapp_connectors.core.dto import WebhookEventType
from bapp_connectors.providers.appstore.apple.adapter import AppleAppStoreAdapter
from bapp_connectors.providers.appstore.apple.errors import AppleWebhookError
from bapp_connectors.providers.appstore.apple.jws import decode_signed_payload, load_root_certificate


def _cert(subject: str, key, issuer_name=None, issuer_key=None, *, ca: bool, not_after=None):
    issuer_key = issuer_key or key
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_name or name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=30))
        .not_valid_after(not_after or now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def chain():
    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert("Test Root", root_key, ca=True)
    inter = _cert("Test Intermediate", inter_key, root.subject, root_key, ca=True)
    leaf = _cert("Test Leaf", leaf_key, inter.subject, inter_key, ca=False)
    root_pem = root.public_bytes(serialization.Encoding.PEM)
    x5c = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (leaf, inter, root)]
    return root_pem, x5c, leaf_key, root_key


def _sign(claims: dict, key, x5c: list[str]) -> str:
    return jwt.encode(claims, key, algorithm="ES256", headers={"x5c": x5c})


def test_decode_valid_chain(chain):
    root_pem, x5c, leaf_key, _ = chain
    token = _sign({"notificationType": "DID_RENEW", "notificationUUID": "u1"}, leaf_key, x5c)
    assert decode_signed_payload(token, root_pem=root_pem)["notificationType"] == "DID_RENEW"


def test_tampered_payload_is_rejected(chain):
    root_pem, x5c, leaf_key, _ = chain
    token = _sign({"notificationType": "DID_RENEW"}, leaf_key, x5c)
    header, _payload, signature = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"notificationType": "REFUND"}).encode()).decode().rstrip("=")
    with pytest.raises(AppleWebhookError):
        decode_signed_payload(f"{header}.{forged}.{signature}", root_pem=root_pem)


def test_chain_not_anchored_in_root_is_rejected(chain):
    root_pem, x5c, leaf_key, _ = chain
    other_root = ec.generate_private_key(ec.SECP256R1())
    other_pem = _cert("Other Root", other_root, ca=True).public_bytes(serialization.Encoding.PEM)
    token = _sign({"notificationType": "DID_RENEW"}, leaf_key, x5c)
    with pytest.raises(AppleWebhookError):
        decode_signed_payload(token, root_pem=other_pem)


def test_expired_leaf_is_rejected(chain):
    root_pem, _, _, root_key = chain
    root = x509.load_pem_x509_certificate(root_pem)
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = _cert("Expired Leaf", leaf_key, root.subject, root_key, ca=False, not_after=datetime.now(UTC) - timedelta(days=1))
    x5c = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (leaf, root)]
    token = _sign({"notificationType": "DID_RENEW"}, leaf_key, x5c)
    with pytest.raises(AppleWebhookError):
        decode_signed_payload(token, root_pem=root_pem)


def test_bundled_root_certificate_fingerprint():
    cert = x509.load_pem_x509_certificate(load_root_certificate())
    assert cert.fingerprint(hashes.SHA256()).hex() == "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"
    assert "Apple Root CA - G3" in cert.subject.rfc4514_string()


def test_adapter_parse_webhook_maps_event(chain, monkeypatch):
    root_pem, x5c, leaf_key, _ = chain
    monkeypatch.setattr("bapp_connectors.providers.appstore.apple.jws.load_root_certificate", lambda: root_pem)
    transaction = _sign({"originalTransactionId": "100", "productId": "ro.cbsoft.pro.monthly", "expiresDate": 1790000000000, "environment": "Production", "bundleId": "ro.cbsoft.app"}, leaf_key, x5c)
    renewal = _sign({"autoRenewStatus": 1, "autoRenewProductId": "ro.cbsoft.pro.monthly"}, leaf_key, x5c)
    outer = _sign(
        {
            "notificationType": "DID_CHANGE_RENEWAL_STATUS",
            "subtype": "AUTO_RENEW_DISABLED",
            "notificationUUID": "uuid-1",
            "version": "2.0",
            "signedDate": 1760000000000,
            "data": {"appAppleId": 645, "bundleId": "ro.cbsoft.app", "environment": "Production", "signedTransactionInfo": transaction, "signedRenewalInfo": renewal},
        },
        leaf_key,
        x5c,
    )
    body = json.dumps({"signedPayload": outer}).encode()
    adapter = AppleAppStoreAdapter(credentials={"issuer_id": "i", "key_id": "k", "private_key": "x", "vendor_number": "1"})
    assert adapter.verify_webhook({}, body) is True
    event = adapter.parse_webhook({}, body)
    assert event.event_type == WebhookEventType.SUBSCRIPTION_CANCELLED
    assert event.idempotency_key == "uuid-1"
    assert event.payload["original_transaction_id"] == "100"
    assert event.payload["product_id"] == "ro.cbsoft.pro.monthly"
    assert event.payload["auto_renew"] is True
    assert event.provider_event_type == "DID_CHANGE_RENEWAL_STATUS/AUTO_RENEW_DISABLED"


def test_adapter_rejects_unsigned_body():
    adapter = AppleAppStoreAdapter(credentials={"issuer_id": "i", "key_id": "k", "private_key": "x", "vendor_number": "1"})
    assert adapter.verify_webhook({}, b'{"notificationType": "REFUND"}') is False
    with pytest.raises(AppleWebhookError):
        adapter.parse_webhook({}, b'{"signedPayload": "a.b.c"}')
