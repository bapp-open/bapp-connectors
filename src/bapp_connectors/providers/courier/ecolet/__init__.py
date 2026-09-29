"""eColet courier-aggregator provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.courier.ecolet.adapter import EcoletCourierAdapter
from bapp_connectors.providers.courier.ecolet.manifest import manifest

__all__ = ["EcoletCourierAdapter", "manifest"]

# Auto-register with the global registry
registry.register(EcoletCourierAdapter)
