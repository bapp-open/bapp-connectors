"""GoIP GSM gateway messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.goip.adapter import GoIPMessagingAdapter
from bapp_connectors.providers.messaging.goip.manifest import manifest

__all__ = ["GoIPMessagingAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GoIPMessagingAdapter)
