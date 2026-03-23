"""eMAG marketplace provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.emag.adapter import EmagShopAdapter
from bapp_connectors.providers.shop.emag.manifest import manifest

__all__ = ["EmagShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(EmagShopAdapter)
