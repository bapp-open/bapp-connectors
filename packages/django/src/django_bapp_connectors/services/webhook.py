"""
Webhook service — receive, verify, deduplicate, dispatch.
"""

from __future__ import annotations

import json
import logging
import uuid

from bapp_connectors.core.errors import WebhookVerificationError
from bapp_connectors.core.webhooks import WebhookDispatcher

logger = logging.getLogger(__name__)

# A rejected webhook is stored for inspection, but anyone who knows the URL can send
# one: cap what a single request can write.
_REJECTED_MAX_CHARS = 16000
_REJECTED_DROP_HEADERS = {"cookie", "authorization"}


def stored_webhook_body(payload) -> bytes:
    """Rebuild the request body from a stored payload, for re-parsing.

    The dispatcher stores a non-JSON body (LibraPay/EuPlatesc post a form) as
    ``{"raw": <text>}``; re-encoding that dict as JSON handed the adapter
    ``{"raw": ...}`` instead of the form, so a LibraPay IPN re-parsed as unknown
    and the checkout never completed.
    """
    if isinstance(payload, dict) and set(payload) == {"raw"} and isinstance(payload["raw"], str):
        return payload["raw"].encode()
    return json.dumps(payload).encode() if isinstance(payload, dict) else b""


class WebhookService:
    """Service layer for webhook processing."""

    def __init__(self, webhook_event_model=None):
        """
        Args:
            webhook_event_model: Your concrete WebhookEvent model class.
        """
        self.webhook_event_model = webhook_event_model
        self._dispatcher = WebhookDispatcher(
            idempotency_checker=self._check_idempotency if webhook_event_model else None,
        )

    def _check_idempotency(self, idempotency_key: str) -> bool:
        """Check if a webhook with this key already exists."""
        if self.webhook_event_model:
            return self.webhook_event_model.objects.filter(idempotency_key=idempotency_key).exists()
        return False

    def _store_rejected(self, provider: str, headers: dict, body: bytes, error: Exception, connection=None):
        """Keep a webhook that failed signature verification, to see what arrived.

        Status "rejected": never processed, and no ``webhook_event_received`` signal
        (a forged IPN must not start a flow). The idempotency key is random, so a
        genuine retry of the same notification is not blocked by it.
        """
        if not self.webhook_event_model:
            return
        try:
            text = body.decode("utf-8", errors="replace")[:_REJECTED_MAX_CHARS] if body else ""
            try:
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    payload = {"raw": text}
            except ValueError:
                payload = {"raw": text}
            create_kwargs = {
                "provider": provider,
                "event_type": "unknown",
                "idempotency_key": f"rejected:{uuid.uuid4().hex}",
                "payload": payload,
                "headers": {k: v for k, v in dict(headers or {}).items() if str(k).lower() not in _REJECTED_DROP_HEADERS},
                "signature_valid": False,
                "status": "rejected",
                "error": str(error)[:2000],
            }
            if connection is not None:
                create_kwargs["connection"] = connection
            self.webhook_event_model.objects.create(**create_kwargs)
        except Exception:
            logger.warning("Could not store rejected webhook for %s", provider, exc_info=True)

    def receive(
        self,
        provider: str,
        headers: dict,
        body: bytes,
        signature_method: str | None = None,
        signature_header: str = "",
        secret: str = "",
        connection=None,
        adapter=None,
    ):
        """
        Process an incoming webhook.

        Returns the persisted WebhookEvent model instance (or the DTO if no model).
        """
        # Parse and verify via the core dispatcher
        try:
            webhook_event = self._dispatcher.receive(
                provider=provider,
                headers=headers,
                body=body,
                signature_method=signature_method,
                signature_header=signature_header,
                secret=secret,
            )
        except WebhookVerificationError as exc:
            self._store_rejected(provider, headers, body, exc, connection)
            raise

        # Adapter normalization (the dispatcher stores UNKNOWN on purpose): overwrite the
        # generic DTO with the provider's own parse BEFORE the duplicate check, so both the
        # stored event_type and the idempotency key are the provider's, not the fallback's.
        if adapter is not None and hasattr(adapter, "parse_webhook"):
            try:
                parsed = adapter.parse_webhook(headers, body)
                if parsed is not None:
                    parsed_type = parsed.event_type.value if hasattr(parsed.event_type, "value") else str(parsed.event_type)
                    if parsed_type and parsed_type != "unknown":
                        webhook_event = webhook_event.model_copy(update={
                            "event_type": parsed.event_type,
                            "provider_event_type": getattr(parsed, "provider_event_type", "") or webhook_event.provider_event_type,
                            "idempotency_key": getattr(parsed, "idempotency_key", "") or webhook_event.idempotency_key,
                        })
            except Exception:
                logger.debug("adapter parse_webhook failed, keeping generic DTO", exc_info=True)

        # Check for duplicates
        if self._dispatcher.is_duplicate(webhook_event.idempotency_key):
            logger.info("Duplicate webhook: %s", webhook_event.idempotency_key)
            if self.webhook_event_model:
                existing = self.webhook_event_model.objects.filter(
                    idempotency_key=webhook_event.idempotency_key,
                ).first()
                if existing:
                    existing.mark_duplicate()
                    return existing
            return webhook_event

        # Persist if model available
        if self.webhook_event_model:
            create_kwargs = {
                "provider": webhook_event.provider,
                "event_type": webhook_event.event_type.value if hasattr(webhook_event.event_type, "value") else str(webhook_event.event_type),
                "idempotency_key": webhook_event.idempotency_key,
                "payload": webhook_event.payload,
                "headers": dict(headers),
                "signature_valid": webhook_event.signature_valid,
                "status": "received",
            }
            if connection is not None:
                create_kwargs["connection"] = connection

            instance = self.webhook_event_model.objects.create(**create_kwargs)

            from django_bapp_connectors.signals import webhook_event_received

            provider_family = ""
            provider_name = ""
            if connection is not None:
                provider_family = getattr(connection, "provider_family", "")
                provider_name = getattr(connection, "provider_name", "")

            webhook_event_received.send_robust(
                sender=self.webhook_event_model,
                webhook_event=instance,
                connection=connection,
                provider_family=provider_family,
                provider_name=provider_name,
            )

            return instance

        return webhook_event
