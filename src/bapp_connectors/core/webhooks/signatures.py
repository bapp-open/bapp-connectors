"""
Webhook signature verification strategies.
"""

from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod


class SignatureVerifier(ABC):
    """Base class for webhook signature verification."""

    @abstractmethod
    def verify(self, body: bytes, signature: str, secret: str) -> bool:
        """Verify the signature against the body and secret."""
        ...


class HmacSha256Verifier(SignatureVerifier):
    """HMAC-SHA256 signature verification.

    Supports multiple header formats:
    - Raw hex: ``abcdef123456...``
    - Prefixed: ``sha256=abcdef123456...``
    - Stripe-style: ``t=1616346610,v1=abcdef123456...``
    """

    def verify(self, body: bytes, signature: str, secret: str) -> bool:
        # Stripe format: "t=<timestamp>,v1=<sig>,..."
        if signature.startswith("t="):
            return self._verify_stripe(body, signature, secret)
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        actual = signature.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, actual)

    @staticmethod
    def _verify_stripe(body: bytes, signature: str, secret: str) -> bool:
        """Stripe signs ``timestamp.body`` and puts the result in the v1= field."""
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        timestamp = parts.get("t", "")
        sig_hex = parts.get("v1", "")
        if not timestamp or not sig_hex:
            return False
        signed_payload = f"{timestamp}.".encode() + body
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig_hex)


class HmacSha1Verifier(SignatureVerifier):
    """HMAC-SHA1 signature verification (used by some legacy APIs)."""

    def verify(self, body: bytes, signature: str, secret: str) -> bool:
        expected = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
        actual = signature.removeprefix("sha1=").strip()
        return hmac.compare_digest(expected, actual)


class NoopVerifier(SignatureVerifier):
    """No verification (for providers that don't sign webhooks)."""

    def verify(self, body: bytes, signature: str, secret: str) -> bool:
        return True


def get_verifier(method: str | None) -> SignatureVerifier:
    """Get a verifier by method name."""
    verifiers: dict[str | None, SignatureVerifier] = {
        None: NoopVerifier(),
        "hmac-sha256": HmacSha256Verifier(),
        "hmac-sha1": HmacSha1Verifier(),
    }
    return verifiers.get(method, NoopVerifier())
