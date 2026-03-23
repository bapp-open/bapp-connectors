"""RoboSMS messaging provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.messaging.robosms.adapter import RoboSMSMessagingAdapter
from bapp_connectors.providers.messaging.robosms.manifest import manifest

__all__ = ["RoboSMSMessagingAdapter", "manifest"]

# Auto-register with the global registry
registry.register(RoboSMSMessagingAdapter)
