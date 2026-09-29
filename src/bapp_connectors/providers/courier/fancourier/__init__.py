"""FAN Courier provider (API v2)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.fancourier.adapter import FanCourierAdapter
from bapp_connectors.providers.courier.fancourier.manifest import manifest

__all__ = ["FanCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(FanCourierAdapter)
