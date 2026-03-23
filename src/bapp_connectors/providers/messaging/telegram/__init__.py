"""Telegram Bot API messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.telegram.adapter import TelegramMessagingAdapter
from bapp_connectors.providers.messaging.telegram.manifest import manifest

__all__ = ["TelegramMessagingAdapter", "manifest"]

# Auto-register with the global registry
registry.register(TelegramMessagingAdapter)
