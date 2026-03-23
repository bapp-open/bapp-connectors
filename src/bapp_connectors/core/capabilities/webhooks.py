"""
Webhook capability — optional interface for providers that support webhooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.webhook import WebhookEvent


class WebhookCapability(ABC):
    """Adapter supports receiving and processing webhooks."""

    @abstractmethod
    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify the signature of an incoming webhook."""
        ...

    @abstractmethod
    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse an incoming webhook payload into a normalized WebhookEvent."""
        ...

    def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """Register a webhook URL with the provider (if supported)."""
        raise NotImplementedError("This provider does not support webhook registration via API.")

    def list_webhooks(self) -> list[dict]:
        """List registered webhooks (if supported)."""
        raise NotImplementedError("This provider does not support webhook listing via API.")
