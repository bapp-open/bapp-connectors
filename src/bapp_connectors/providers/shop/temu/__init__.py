"""Temu marketplace provider (Partner Platform, local-to-local sellers)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.temu.adapter import TemuShopAdapter
from bapp_connectors.providers.shop.temu.manifest import manifest

__all__ = ["TemuShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(TemuShopAdapter)
