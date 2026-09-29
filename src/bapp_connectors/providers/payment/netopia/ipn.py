"""
Netopia IPN signature verification.

Netopia signs every IPN with a JWT in the ``Verification-Token`` header, the
same checks the official SDKs (netopiapayments/composer IPN.php, netopia_sdk
ipn.py) make:

- RS512 signature with the merchant's Netopia public key
- ``iss`` == "NETOPIA Payments"
- ``aud`` (string, or first item of a list) == the POS signature
- ``sub`` == base64(sha512(raw body)) — ties the token to this exact payload

Stricter than the SDKs on purpose: the algorithm is pinned to RS512 instead of
taken from the token header, and a missing public key fails instead of passing.

The signing key is Netopia's own and the same for every merchant, live and
sandbox: the official WooCommerce and OpenCart plugins ship it hardcoded
(``NETOPIA_IPN_PUBLIC_KEY``). The per-POS ``live.<POS>.public.cer`` from the
admin panel is the legacy mobilPay (v1) encryption certificate, not this key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

NETOPIA_IPN_HEADER = "Verification-Token"
NETOPIA_ISSUER = "NETOPIA Payments"
EXPIRY_LEEWAY_SECONDS = 300

# From netopiapayments/WooCommerce v2/wc-netopiapayments-gateway.php and
# netopiapayments/opencart-plugin catalog/controller/payment/mobilpay.php.
NETOPIA_IPN_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAy6pUDAFLVul4y499gz1P
gGSvTSc82U3/ih3e5FDUs/F0Jvfzc4cew8TrBDrw7Y+AYZS37D2i+Xi5nYpzQpu7
ryS4W+qvgAA1SEjiU1Sk2a4+A1HeH+vfZo0gDrIYTh2NSAQnDSDxk5T475ukSSwX
L9tYwO6CpdAv3BtpMT5YhyS3ipgPEnGIQKXjh8GMgLSmRFbgoCTRWlCvu7XOg94N
fS8l4it2qrEldU8VEdfPDfFLlxl3lUoLEmCncCjmF1wRVtk4cNu+WtWQ4mBgxpt0
tX2aJkqp4PV3o5kI4bqHq/MS7HVJ7yxtj/p8kawlVYipGsQj3ypgltQ3bnYV/LRq
8QIDAQAB
-----END PUBLIC KEY-----
"""

_PEM_RE = re.compile(r"-----BEGIN ([A-Z ]+)-----(.*?)-----END \1-----", re.DOTALL)


class NetopiaIpnVerificationError(Exception):
    """The IPN token failed one of the checks; the message says which."""


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def load_public_key(text: str):
    """Load a Netopia public key from a PEM certificate, PEM public key, or bare base64.

    Connection forms often flatten the pasted PEM onto one line, so the body is
    re-extracted and whitespace-stripped rather than parsed as-is.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    text = (text or "").strip()
    if not text:
        raise NetopiaIpnVerificationError("public key is not configured")
    match = _PEM_RE.search(text)
    label, body = (match.group(1), match.group(2)) if match else ("", text)
    try:
        der = base64.b64decode("".join(body.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise NetopiaIpnVerificationError("public key is not valid base64/PEM") from exc

    loaders = [x509.load_der_x509_certificate, load_der_public_key]
    if label == "PUBLIC KEY":
        loaders.reverse()
    for loader in loaders:
        try:
            loaded = loader(der)
        except ValueError:
            continue
        return loaded.public_key() if hasattr(loaded, "public_key") else loaded
    raise NetopiaIpnVerificationError("public key is neither an X.509 certificate nor a public key")


def get_header(headers: dict, name: str) -> str:
    """Case-insensitive header lookup (Netopia sends ``Verification-token``)."""
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == lowered:
            return str(value)
    return ""


def _to_seconds(value: float) -> float:
    # The PHP SDK runs its JWT clock in milliseconds; accept either unit.
    return value / 1000 if value > 1e11 else value


def verify_ipn_token(token: str, body: bytes, pos_signature: str, public_keys: list[str] | None = None) -> dict:
    """Verify a Netopia IPN token against the raw body. Returns the claims or raises.

    ``public_keys`` defaults to Netopia's published key; an override (key
    rotation, tests) is tried as given.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    if not pos_signature:
        raise NetopiaIpnVerificationError("POS signature is not configured")
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise NetopiaIpnVerificationError(f"missing or malformed {NETOPIA_IPN_HEADER} header")
    head_b64, claims_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(head_b64))
        claims = json.loads(_b64url_decode(claims_b64))
        signature = _b64url_decode(sig_b64)
    except (binascii.Error, ValueError) as exc:
        raise NetopiaIpnVerificationError("token is not valid base64url JSON") from exc

    if header.get("alg") != "RS512":
        raise NetopiaIpnVerificationError(f"unexpected token algorithm {header.get('alg')!r}")

    signed = f"{head_b64}.{claims_b64}".encode()
    for key_text in public_keys or [NETOPIA_IPN_PUBLIC_KEY]:
        try:
            load_public_key(key_text).verify(signature, signed, padding.PKCS1v15(), hashes.SHA512())
            break
        except (InvalidSignature, NetopiaIpnVerificationError):
            continue
    else:
        raise NetopiaIpnVerificationError("token signature does not match Netopia's public key")

    if claims.get("iss") != NETOPIA_ISSUER:
        raise NetopiaIpnVerificationError(f"unexpected issuer {claims.get('iss')!r}")
    aud = claims.get("aud")
    aud = aud[0] if isinstance(aud, list) and aud else aud
    if aud != pos_signature:
        raise NetopiaIpnVerificationError("token audience is not this POS signature")
    body_hash = base64.b64encode(hashlib.sha512(body).digest()).decode()
    if claims.get("sub") != body_hash:
        raise NetopiaIpnVerificationError("payload hash does not match the token (body tampered)")
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and _to_seconds(exp) + EXPIRY_LEEWAY_SECONDS < time.time():
        raise NetopiaIpnVerificationError("token expired")
    return claims
