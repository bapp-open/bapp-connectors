"""Company Store (BAPP) shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from bapp_connectors.providers.shop.bapp_store.manifest import manifest

__all__ = ["BappStoreShopAdapter", "manifest"]

registry.register(BappStoreShopAdapter)
