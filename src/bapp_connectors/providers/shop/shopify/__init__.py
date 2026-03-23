"""Shopify Admin REST API shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.shopify.adapter import ShopifyShopAdapter
from bapp_connectors.providers.shop.shopify.manifest import manifest

__all__ = ["ShopifyShopAdapter", "manifest"]

registry.register(ShopifyShopAdapter)
