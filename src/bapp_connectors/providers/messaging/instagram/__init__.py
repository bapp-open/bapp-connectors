"""Instagram DM messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.instagram.adapter import InstagramMessagingAdapter
from bapp_connectors.providers.messaging.instagram.manifest import manifest

__all__ = ["InstagramMessagingAdapter", "manifest"]

registry.register(InstagramMessagingAdapter)
