"""
Webhook dispatcher — routes incoming webhooks, verifies signatures, and deduplicates.

Framework-agnostic: no Django dependency. The Django layer wraps this with views/models.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable

from bapp_connectors.core.dto.webhook import WebhookEvent, WebhookEventType
from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.webhooks.signatures import get_verifier

logger = logging.getLogger(__name__)

# Type for idempotency check callback: (idempotency_key) -> bool (True = already seen)
IdempotencyChecker = Callable[[str], bool]


class WebhookDispatcher:
    """
    Routes incoming webhooks to the correct adapter for parsing.

    Handles:
    - Signature verification
    - Deduplication via idempotency keys
    - Normalization to WebhookEvent DTO
    """

    def __init__(self, idempotency_checker: IdempotencyChecker | None = None):
        """
        Args:
            idempotency_checker: Optional callback that returns True if an idempotency key
                                 has already been processed. Used for deduplication.
        """
        self._idempotency_checker = idempotency_checker

    @staticmethod
    def compute_idempotency_key(provider: str, body: bytes) -> str:
        """Generate a deterministic idempotency key from provider + body hash."""
        body_hash = hashlib.sha256(body).hexdigest()[:16]
        return f"{provider}:{body_hash}"

    def verify_signature(
        self,
        signature_method: str | None,
        headers: dict,
        body: bytes,
        secret: str,
        signature_header: str = "",
    ) -> bool:
        """Verify webhook signature using the provider's declared method."""
        if not signature_method:
            return True  # Provider doesn't sign webhooks

        signature = headers.get(signature_header, "")
        if not signature:
            raise WebhookVerificationError(f"Missing signature header: {signature_header}")

        verifier = get_verifier(signature_method)
        if not verifier.verify(body, signature, secret):
            raise WebhookVerificationError("Webhook signature verification failed.")

        return True

    def is_duplicate(self, idempotency_key: str) -> bool:
        """Check if this webhook has already been processed."""
        if self._idempotency_checker:
            return self._idempotency_checker(idempotency_key)
        return False

    def receive(
        self,
        provider: str,
        headers: dict,
        body: bytes,
        signature_method: str | None = None,
        signature_header: str = "",
        secret: str = "",
    ) -> WebhookEvent:
        """
        Process an incoming webhook: verify, deduplicate, and parse into a WebhookEvent.

        Args:
            provider: Provider name (e.g., 'trendyol').
            headers: HTTP headers from the webhook request.
            body: Raw request body bytes.
            signature_method: Signature method from manifest (e.g., 'hmac-sha256').
            signature_header: Header name containing the signature.
            secret: Webhook secret for verification.

        Returns:
            Normalized WebhookEvent DTO.
        """
        # Verify signature
        is_valid = True
        try:
            self.verify_signature(signature_method, headers, body, secret, signature_header)
        except WebhookVerificationError:
            is_valid = False
            raise

        # Compute idempotency key
        idempotency_key = self.compute_idempotency_key(provider, body)

        # Parse body
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"raw": body.decode("utf-8", errors="replace")}

        return WebhookEvent(
            provider=provider,
            event_type=WebhookEventType.UNKNOWN,  # adapter normalizes this
            provider_event_type="",
            payload=payload,
            idempotency_key=idempotency_key,
            signature_valid=is_valid,
        )
