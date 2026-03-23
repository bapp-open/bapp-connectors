"""Vendigo marketplace provider."""

from __future__ import annotations

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.vendigo.adapter import VendigoShopAdapter
from bapp_connectors.providers.shop.vendigo.manifest import manifest

__all__ = ["VendigoShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(VendigoShopAdapter)
