"""Trendyol marketplace provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.trendyol.adapter import TrendyolShopAdapter
from bapp_connectors.providers.shop.trendyol.manifest import manifest

__all__ = ["TrendyolShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(TrendyolShopAdapter)
