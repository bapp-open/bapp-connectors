"""Facebook Messenger messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.messenger.adapter import MessengerMessagingAdapter
from bapp_connectors.providers.messaging.messenger.manifest import manifest

__all__ = ["MessengerMessagingAdapter", "manifest"]

registry.register(MessengerMessagingAdapter)
