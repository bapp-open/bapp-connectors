"""
Re-exports webhook event types from the DTO layer.
"""

from bapp_connectors.core.dto.webhook import WebhookEvent, WebhookEventType

__all__ = ["WebhookEvent", "WebhookEventType"]
