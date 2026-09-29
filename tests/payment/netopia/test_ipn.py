"""
Netopia IPN signature verification — tokens signed here the way Netopia signs
them (RS512 JWT in Verification-Token, sub = base64(sha512(body))). The test key
is passed as the ``public_key`` override, since only Netopia holds its private key.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.webhooks import WebhookDispatcher, get_verifier
from bapp_connectors.providers.payment.netopia.adapter import NetopiaPaymentAdapter
from bapp_connectors.providers.payment.netopia.manifest import manifest

POS = "30AD-TEST-POS1-SIG0-0000"
BODY = json.dumps({"order": {"orderID": "O-1"}, "payment": {"ntpID": "NTP1", "status": 3}}).encode()

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _cert_pem(key) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NETOPIA Payments test")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


CERT_PEM = _cert_pem(_KEY)
PUBKEY_PEM = _KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(body: bytes = BODY, *, key=_KEY, alg: str = "RS512", **claim_overrides) -> str:
    claims = {
        "iss": "NETOPIA Payments",
        "aud": [POS],
        "sub": base64.b64encode(hashlib.sha512(body).digest()).decode(),
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
    }
    claims.update(claim_overrides)
    head = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(json.dumps(claims).encode())
    signature = key.sign(f"{head}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA512())
    return f"{head}.{payload}.{_b64url(signature)}"


def adapter(public_key: str = CERT_PEM, pos: str = POS) -> NetopiaPaymentAdapter:
    return NetopiaPaymentAdapter(credentials={"api_key": "k", "pos_signature": pos, "public_key": public_key})


class TestValidIpn:

    def test_certificate_key(self):
        assert adapter().verify_webhook({"Verification-Token": make_token()}, BODY) is True

    def test_bare_public_key(self):
        assert adapter(PUBKEY_PEM).verify_webhook({"Verification-Token": make_token()}, BODY) is True

    def test_pem_flattened_to_one_line_by_a_form(self):
        flat = " ".join(CERT_PEM.splitlines())
        assert adapter(flat).verify_webhook({"Verification-Token": make_token()}, BODY) is True

    def test_header_name_is_case_insensitive(self):
        # Netopia sends "Verification-token"; Django title-cases it.
        assert adapter().verify_webhook({"verification-token": make_token()}, BODY) is True

    def test_audience_as_plain_string(self):
        assert adapter().verify_webhook({"Verification-Token": make_token(aud=POS)}, BODY) is True

    def test_expiry_in_milliseconds(self):
        token = make_token(exp=int(time.time() * 1000) + 600_000)
        assert adapter().verify_webhook({"Verification-Token": token}, BODY) is True


class TestRejectedIpn:

    @pytest.mark.parametrize(
        "headers,body",
        [
            ({}, BODY),  # no token at all: the forged IPN this closes
            ({"Verification-Token": "not.a.jwt.token"}, BODY),
            ({"Verification-Token": make_token()}, BODY.replace(b'"status": 3', b'"status": 5')),  # tampered
            ({"Verification-Token": make_token(key=_OTHER_KEY)}, BODY),  # signed by someone else
            ({"Verification-Token": make_token(aud=["OTHER-POS"])}, BODY),  # another merchant's IPN
            ({"Verification-Token": make_token(iss="evil")}, BODY),
            ({"Verification-Token": make_token(exp=int(time.time()) - 3600)}, BODY),
            ({"Verification-Token": make_token(alg="RS256")}, BODY),  # algorithm pinned to RS512
        ],
        ids=["missing", "malformed", "tampered", "wrong-key", "wrong-aud", "wrong-iss", "expired", "alg"],
    )
    def test_rejected(self, headers, body):
        assert adapter().verify_webhook(headers, body) is False

    def test_alg_none_rejected(self):
        head = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
        claims = _b64url(json.dumps({"iss": "NETOPIA Payments", "aud": [POS],
                                     "sub": base64.b64encode(hashlib.sha512(BODY).digest()).decode()}).encode())
        assert adapter().verify_webhook({"Verification-Token": f"{head}.{claims}."}, BODY) is False

    def test_without_override_only_netopias_key_is_trusted(self):
        # Our test key is not Netopia's, so with no override the token must fail.
        assert adapter(public_key="").verify_webhook({"Verification-Token": make_token()}, BODY) is False

    def test_garbage_override_falls_back_to_netopias_key_and_still_rejects(self):
        assert adapter(public_key="not a key").verify_webhook({"Verification-Token": make_token()}, BODY) is False


class TestNetopiaPublishedKey:

    def test_published_key_loads(self):
        from bapp_connectors.providers.payment.netopia.ipn import NETOPIA_IPN_PUBLIC_KEY, load_public_key

        assert load_public_key(NETOPIA_IPN_PUBLIC_KEY).key_size == 2048

    def test_connection_form_does_not_ask_for_a_key(self):
        assert "public_key" not in {f.name for f in manifest.auth.required_fields}


class TestIpnAcknowledgement:
    """errorType drives Netopia's resend: 0 recorded, 1 retry, 2 give up."""

    @pytest.mark.parametrize("outcome,error_type", [("ok", 0), ("error", 1), ("rejected", 2)])
    def test_error_type(self, outcome, error_type):
        assert adapter().webhook_response(outcome)["errorType"] == error_type

    def test_ok_has_no_error_code(self):
        assert adapter().webhook_response("ok") == {"errorType": 0, "errorCode": None, "errorMessage": ""}


class TestGenericPathFailsClosed:
    """If a host skips the adapter, the generic verifier must not wave it through."""

    def test_manifest_declares_adapter_verified_method(self):
        assert manifest.webhooks.signature_method == "netopia-jwt"
        assert manifest.webhooks.signature_header == "Verification-Token"

    def test_generic_verifier_rejects(self):
        assert get_verifier("netopia-jwt").verify(BODY, make_token(), "") is False

    def test_dispatcher_raises(self):
        with pytest.raises(WebhookVerificationError):
            WebhookDispatcher().receive(
                provider="netopia",
                headers={"Verification-Token": make_token()},
                body=BODY,
                signature_method="netopia-jwt",
                signature_header="Verification-Token",
            )
