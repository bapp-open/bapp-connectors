"""Gomag shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.gomag.adapter import GomagShopAdapter
from bapp_connectors.providers.shop.gomag.manifest import manifest

__all__ = ["GomagShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(GomagShopAdapter)
