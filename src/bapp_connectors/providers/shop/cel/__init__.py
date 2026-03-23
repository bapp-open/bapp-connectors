"""CEL.ro marketplace provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.cel.adapter import CelShopAdapter
from bapp_connectors.providers.shop.cel.manifest import manifest

__all__ = ["CelShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(CelShopAdapter)
