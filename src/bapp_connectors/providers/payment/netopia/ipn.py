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


def verify_ipn_token(token: str, body: bytes, public_key_text: str, pos_signature: str) -> dict:
    """Verify a Netopia IPN token against the raw body. Returns the claims or raises."""
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

    public_key = load_public_key(public_key_text)
    try:
        public_key.verify(signature, f"{head_b64}.{claims_b64}".encode(), padding.PKCS1v15(), hashes.SHA512())
    except InvalidSignature as exc:
        raise NetopiaIpnVerificationError("token signature does not match the public key") from exc

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
