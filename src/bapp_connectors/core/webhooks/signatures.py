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
    """HMAC-SHA256 signature verification (used by Stripe, Dropbox, etc.)."""

    def verify(self, body: bytes, signature: str, secret: str) -> bool:
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        # Handle common prefix formats: "sha256=..." or raw hex
        actual = signature.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, actual)


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
