"""Magento 2 / Adobe Commerce shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.magento.adapter import MagentoShopAdapter
from bapp_connectors.providers.shop.magento.manifest import manifest

__all__ = ["MagentoShopAdapter", "manifest"]

registry.register(MagentoShopAdapter)
