"""
Shopify Admin REST API client.

Auth: X-Shopify-Access-Token header.
All responses wrap in {"product": {...}}, {"products": [...]}, etc.
Pagination: Link header with page_info cursor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.ai import ai_method

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


# Documented GET products.json filters an agent may send.
AI_PRODUCT_FILTERS = (
    "ids", "title", "vendor", "product_type", "collection_id", "handle", "status", "created_at_min", "created_at_max",
    "updated_at_min", "updated_at_max", "published_status", "fields", "page_info",
)
# Documented GET orders.json filters an agent may send.
AI_ORDER_FILTERS = (
    "ids", "name", "financial_status", "fulfillment_status", "created_at_min", "created_at_max", "updated_at_min",
    "updated_at_max", "processed_at_min", "processed_at_max", "fields", "page_info",
)


class ShopifyApiClient:
    """Low-level Shopify Admin API client."""

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _call(self, method: str, path: str, **kwargs):
        return self.http.call(method, path, **kwargs)

    # ── Auth ──

    def test_auth(self) -> bool:
        try:
            self._call("GET", "shop.json")
            return True
        except Exception:
            return False

    # ── Products ──

    @ai_method(
        "read",
        "Products, one page per call (limit up to 250, continue with since_id); params adds Shopify filters.",
        extra={"params": "flat"},
        allowed_keys={"params": AI_PRODUCT_FILTERS},
    )
    def get_products(self, limit: int = 250, since_id: int | None = None, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if since_id is not None:
            params["since_id"] = since_id
        params.update(kwargs.pop("params", {}))
        result = self._call("GET", "products.json", params=params, **kwargs)
        return result.get("products", []) if isinstance(result, dict) else []

    @ai_method("read", "One product by id.")
    def get_product(self, product_id: int, **kwargs) -> dict:
        result = self._call("GET", f"products/{product_id}.json", **kwargs)
        return result.get("product", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Create a product.")
    def create_product(self, data: dict, **kwargs) -> dict:
        result = self._call("POST", "products.json", json={"product": data}, **kwargs)
        return result.get("product", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Update a product.")
    def update_product(self, product_id: int, data: dict, **kwargs) -> dict:
        result = self._call("PUT", f"products/{product_id}.json", json={"product": data}, **kwargs)
        return result.get("product", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Delete a product.")
    def delete_product(self, product_id: int, **kwargs) -> bool:
        self._call("DELETE", f"products/{product_id}.json", **kwargs)
        return True

    @ai_method("read", "The number of products in the store.")
    def count_products(self, **kwargs) -> int:
        result = self._call("GET", "products/count.json", **kwargs)
        return result.get("count", 0) if isinstance(result, dict) else 0

    # ── Variants ──

    @ai_method("read", "The variants of one product, in one call.")
    def get_variants(self, product_id: int, **kwargs) -> list[dict]:
        result = self._call("GET", f"products/{product_id}/variants.json", **kwargs)
        return result.get("variants", []) if isinstance(result, dict) else []

    @ai_method("read", "One variant by id.")
    def get_variant(self, variant_id: int, **kwargs) -> dict:
        result = self._call("GET", f"variants/{variant_id}.json", **kwargs)
        return result.get("variant", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Create a variant on a product.")
    def create_variant(self, product_id: int, data: dict, **kwargs) -> dict:
        result = self._call("POST", f"products/{product_id}/variants.json", json={"variant": data}, **kwargs)
        return result.get("variant", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Update a variant.")
    def update_variant(self, variant_id: int, data: dict, **kwargs) -> dict:
        result = self._call("PUT", f"variants/{variant_id}.json", json={"variant": data}, **kwargs)
        return result.get("variant", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Delete a variant.")
    def delete_variant(self, product_id: int, variant_id: int, **kwargs) -> bool:
        self._call("DELETE", f"products/{product_id}/variants/{variant_id}.json", **kwargs)
        return True

    # ── Orders ──

    @ai_method(
        "read",
        "Orders, one page per call (limit up to 250, continue with since_id), by status; params adds Shopify filters.",
        extra={"params": "flat"},
        allowed_keys={"params": AI_ORDER_FILTERS},
    )
    def get_orders(self, limit: int = 250, status: str = "any", since_id: int | None = None, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "status": status}
        if since_id is not None:
            params["since_id"] = since_id
        params.update(kwargs.pop("params", {}))
        result = self._call("GET", "orders.json", params=params, **kwargs)
        return result.get("orders", []) if isinstance(result, dict) else []

    @ai_method("read", "One order by id.")
    def get_order(self, order_id: int, **kwargs) -> dict:
        result = self._call("GET", f"orders/{order_id}.json", **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Update an order.")
    def update_order(self, order_id: int, data: dict, **kwargs) -> dict:
        result = self._call("PUT", f"orders/{order_id}.json", json={"order": data}, **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Cancel an order.")
    def cancel_order(self, order_id: int, **kwargs) -> dict:
        result = self._call("POST", f"orders/{order_id}/cancel.json", **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Close an order.")
    def close_order(self, order_id: int, **kwargs) -> dict:
        result = self._call("POST", f"orders/{order_id}/close.json", **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Reopen a closed order.")
    def reopen_order(self, order_id: int, **kwargs) -> dict:
        result = self._call("POST", f"orders/{order_id}/open.json", **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    # ── Custom Collections ──

    @ai_method("read", "Custom collections (first page), in one call.")
    def get_custom_collections(self, **kwargs) -> list[dict]:
        result = self._call("GET", "custom_collections.json", **kwargs)
        return result.get("custom_collections", []) if isinstance(result, dict) else []

    @ai_method("write", "Create a custom collection.")
    def create_custom_collection(self, data: dict, **kwargs) -> dict:
        result = self._call("POST", "custom_collections.json", json={"custom_collection": data}, **kwargs)
        return result.get("custom_collection", {}) if isinstance(result, dict) else {}

    @ai_method("write", "Delete a custom collection.")
    def delete_custom_collection(self, collection_id: int, **kwargs) -> bool:
        self._call("DELETE", f"custom_collections/{collection_id}.json", **kwargs)
        return True

    # ── Smart Collections ──

    @ai_method("read", "Smart collections (first page), in one call.")
    def get_smart_collections(self, **kwargs) -> list[dict]:
        result = self._call("GET", "smart_collections.json", **kwargs)
        return result.get("smart_collections", []) if isinstance(result, dict) else []

    # ── Webhooks ──

    def get_webhooks(self, **kwargs) -> list[dict]:
        result = self._call("GET", "webhooks.json", **kwargs)
        return result.get("webhooks", []) if isinstance(result, dict) else []

    def create_webhook(self, data: dict, **kwargs) -> dict:
        result = self._call("POST", "webhooks.json", json={"webhook": data}, **kwargs)
        return result.get("webhook", {}) if isinstance(result, dict) else {}

    def delete_webhook(self, webhook_id: int, **kwargs) -> bool:
        self._call("DELETE", f"webhooks/{webhook_id}.json", **kwargs)
        return True

    # ── Inventory ──

    @ai_method("read", "The inventory levels of one inventory item, per location.")
    def get_inventory_level(self, inventory_item_id: int, **kwargs) -> list[dict]:
        result = self._call("GET", "inventory_levels.json", params={"inventory_item_ids": str(inventory_item_id)}, **kwargs)
        return result.get("inventory_levels", []) if isinstance(result, dict) else []

    @ai_method("write", "Set the available quantity of an inventory item at a location.")
    def set_inventory_level(self, data: dict, **kwargs) -> dict:
        result = self._call("POST", "inventory_levels/set.json", json=data, **kwargs)
        return result.get("inventory_level", {}) if isinstance(result, dict) else {}
