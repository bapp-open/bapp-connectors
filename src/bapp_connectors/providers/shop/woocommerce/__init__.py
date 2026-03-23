"""WooCommerce shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from bapp_connectors.providers.shop.woocommerce.manifest import manifest

__all__ = ["WooCommerceShopAdapter", "manifest"]

# Auto-register with the global registry
registry.register(WooCommerceShopAdapter)
