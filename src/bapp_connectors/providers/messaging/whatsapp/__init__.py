"""WhatsApp Business Cloud API messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.whatsapp.adapter import WhatsAppMessagingAdapter
from bapp_connectors.providers.messaging.whatsapp.manifest import manifest

__all__ = ["WhatsAppMessagingAdapter", "manifest"]

# Auto-register with the global registry
registry.register(WhatsAppMessagingAdapter)
