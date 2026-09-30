"""Altex Marketplace provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.altex.adapter import AltexShopAdapter
from bapp_connectors.providers.shop.altex.manifest import manifest

__all__ = ["AltexShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(AltexShopAdapter)
