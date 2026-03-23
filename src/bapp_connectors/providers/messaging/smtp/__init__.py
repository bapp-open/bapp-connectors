"""SMTP email messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.smtp.adapter import SMTPMessagingAdapter
from bapp_connectors.providers.messaging.smtp.manifest import manifest

__all__ = ["SMTPMessagingAdapter", "manifest"]

# Auto-register with the global registry
registry.register(SMTPMessagingAdapter)
