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

LEAF_OID = "1.2.840.113635.100.6.11.1"
INTER_OID = "1.2.840.113635.100.6.2.1"


def _cert(subject: str, key, issuer_name=None, issuer_key=None, *, ca: bool, not_after=None, extra_oids=None):
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
    for oid in extra_oids or []:
        builder = builder.add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier(oid), b"\x05\x00"), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def chain():
    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert("Test Root", root_key, ca=True)
    inter = _cert("Test Intermediate", inter_key, root.subject, root_key, ca=True, extra_oids=[INTER_OID])
    leaf = _cert("Test Leaf", leaf_key, inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
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


def _x5c(*certs) -> list[str]:
    return [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in certs]


def _parts(chain):
    root_pem, _, _, root_key = chain
    root = x509.load_pem_x509_certificate(root_pem)
    inter_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    return root_pem, root, root_key, inter_key, leaf_key


def _reject(token, root_pem):
    with pytest.raises(AppleWebhookError):
        decode_signed_payload(token, root_pem=root_pem)


def test_expired_leaf_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True, extra_oids=[INTER_OID])
    leaf = _cert("Expired Leaf", leaf_key, inter.subject, inter_key, ca=False, not_after=datetime.now(UTC) - timedelta(days=1), extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf, inter, root)), root_pem)


def test_expired_intermediate_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True, not_after=datetime.now(UTC) - timedelta(days=1), extra_oids=[INTER_OID])
    leaf = _cert("Leaf", leaf_key, inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf, inter, root)), root_pem)


def test_leaf_issued_by_non_ca_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True, extra_oids=[INTER_OID])
    leaf = _cert("Leaf", leaf_key, inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
    # 4 certificate: evil emis de leaf (ca=False)
    evil_key = ec.generate_private_key(ec.SECP256R1())
    evil = _cert("Evil", evil_key, leaf.subject, leaf_key, ca=False, extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, evil_key, _x5c(evil, leaf, inter, root)), root_pem)
    # 3 certificate, "intermediarul" are ca=False
    fake_inter = _cert("FakeInter", inter_key, root.subject, root_key, ca=False, extra_oids=[INTER_OID])
    leaf2 = _cert("Leaf", leaf_key, fake_inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf2, fake_inter, root)), root_pem)


def test_missing_leaf_oid_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True, extra_oids=[INTER_OID])
    leaf = _cert("Leaf", leaf_key, inter.subject, inter_key, ca=False)
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf, inter, root)), root_pem)


def test_missing_intermediate_oid_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True)
    leaf = _cert("Leaf", leaf_key, inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf, inter, root)), root_pem)


def test_chain_without_root_is_rejected(chain):
    root_pem, root, root_key, inter_key, leaf_key = _parts(chain)
    inter = _cert("Inter", inter_key, root.subject, root_key, ca=True, extra_oids=[INTER_OID])
    leaf = _cert("Leaf", leaf_key, inter.subject, inter_key, ca=False, extra_oids=[LEAF_OID])
    _reject(_sign({"notificationType": "DID_RENEW"}, leaf_key, _x5c(leaf, inter)), root_pem)


def test_alg_none_is_rejected(chain):
    root_pem, x5c, _, _ = chain
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT", "x5c": x5c}).encode()).decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps({"notificationType": "REFUND"}).encode()).decode().rstrip("=")
    _reject(f"{header}.{body}.", root_pem)


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


def _outer(chain, data, env="Production"):
    root_pem, x5c, leaf_key, _ = chain
    return root_pem, json.dumps({"signedPayload": _sign({"notificationType": "DID_RENEW", "notificationUUID": "u", "data": data}, leaf_key, x5c)}).encode()


_CREDS = {"issuer_id": "i", "key_id": "k", "private_key": "x", "vendor_number": "1"}


def test_other_bundle_id_is_rejected(chain, monkeypatch):
    root_pem, body = _outer(chain, {"bundleId": "evil.app", "environment": "Production"})
    monkeypatch.setattr("bapp_connectors.providers.appstore.apple.jws.load_root_certificate", lambda: root_pem)
    adapter = AppleAppStoreAdapter(credentials={**_CREDS, "bundle_id": "ro.cbsoft.app"})
    assert adapter.verify_webhook({}, body) is False
    with pytest.raises(AppleWebhookError):
        adapter.parse_webhook({}, body)


def test_sandbox_notification_rejected_in_production(chain, monkeypatch):
    root_pem, body = _outer(chain, {"bundleId": "ro.cbsoft.app", "environment": "Sandbox"})
    monkeypatch.setattr("bapp_connectors.providers.appstore.apple.jws.load_root_certificate", lambda: root_pem)
    adapter = AppleAppStoreAdapter(credentials={**_CREDS, "bundle_id": "ro.cbsoft.app"})
    assert adapter.verify_webhook({}, body) is False


def test_sandbox_accepted_when_configured(chain, monkeypatch):
    root_pem, body = _outer(chain, {"bundleId": "ro.cbsoft.app", "environment": "Sandbox"})
    monkeypatch.setattr("bapp_connectors.providers.appstore.apple.jws.load_root_certificate", lambda: root_pem)
    adapter = AppleAppStoreAdapter(credentials={**_CREDS, "bundle_id": "ro.cbsoft.app"}, config={"server_api_environment": "sandbox"})
    assert adapter.verify_webhook({}, body) is True


def test_verify_webhook_returns_false_on_malformed_data(chain, monkeypatch):
    root_pem, body = _outer(chain, "str")
    monkeypatch.setattr("bapp_connectors.providers.appstore.apple.jws.load_root_certificate", lambda: root_pem)
    adapter = AppleAppStoreAdapter(credentials=_CREDS)
    assert adapter.verify_webhook({}, body) is False
    with pytest.raises(AppleWebhookError):
        adapter.parse_webhook({}, body)
