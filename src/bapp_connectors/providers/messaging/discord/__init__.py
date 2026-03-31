"""Discord Bot API messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.discord.adapter import DiscordMessagingAdapter
from bapp_connectors.providers.messaging.discord.manifest import manifest

__all__ = ["DiscordMessagingAdapter", "manifest"]

registry.register(DiscordMessagingAdapter)
