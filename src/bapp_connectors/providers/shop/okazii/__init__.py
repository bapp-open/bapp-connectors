"""Okazii marketplace provider."""

from __future__ import annotations

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.okazii.adapter import OkaziiShopAdapter
from bapp_connectors.providers.shop.okazii.manifest import manifest

__all__ = ["OkaziiShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(OkaziiShopAdapter)
