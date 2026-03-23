"""PrestaShop webservice provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.prestashop.adapter import PrestaShopShopAdapter
from bapp_connectors.providers.shop.prestashop.manifest import manifest

__all__ = ["PrestaShopShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(PrestaShopShopAdapter)
