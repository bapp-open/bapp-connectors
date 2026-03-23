"""
Magento 2 REST API client — raw HTTP calls only.

Auth: Bearer token in Authorization header.
Magento uses SKU-based product identification (not numeric IDs).
All list endpoints use searchCriteria query parameters.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class MagentoApiClient:
    """
    Low-level Magento 2 API client.

    Key Magento API differences from WooCommerce/PrestaShop:
    - Products are identified by SKU (not numeric ID)
    - List endpoints return {items: [], total_count, search_criteria}
    - Pagination via searchCriteria[pageSize] + searchCriteria[currentPage]
    - Categories use a tree structure (not flat list)
    - Stock updates go through /products/{sku}/stockItems/{itemId}
    - Order status changes via POST /orders/{id}/comments
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    @staticmethod
    def _search_params(
        page: int = 1,
        page_size: int = 100,
        filters: list[dict] | None = None,
        sort_field: str = "entity_id",
        sort_dir: str = "ASC",
    ) -> dict[str, str]:
        """Build Magento searchCriteria query parameters."""
        params: dict[str, str] = {
            "searchCriteria[pageSize]": str(page_size),
            "searchCriteria[currentPage]": str(page),
            "searchCriteria[sortOrders][0][field]": sort_field,
            "searchCriteria[sortOrders][0][direction]": sort_dir,
        }
        for i, f in enumerate(filters or []):
            group = f.get("group", 0)
            params[f"searchCriteria[filterGroups][{group}][filters][{i}][field]"] = f["field"]
            params[f"searchCriteria[filterGroups][{group}][filters][{i}][value]"] = str(f["value"])
            params[f"searchCriteria[filterGroups][{group}][filters][{i}][conditionType]"] = f.get("condition", "eq")
        return params

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by fetching store config."""
        try:
            self.http.call("GET", "store/storeConfigs")
            return True
        except Exception:
            return False

    # ── Products (SKU-based) ──

    def get_products(self, page: int = 1, page_size: int = 100, filters: list[dict] | None = None) -> dict:
        """GET /products — list products with searchCriteria."""
        params = self._search_params(page=page, page_size=page_size, filters=filters, sort_field="updated_at", sort_dir="DESC")
        return self.http.call("GET", "products", params=params)

    def get_product(self, sku: str) -> dict:
        """GET /products/{sku} — fetch a single product by SKU."""
        return self.http.call("GET", f"products/{quote(sku, safe='')}")

    def create_product(self, data: dict) -> dict:
        """POST /products — create a product."""
        return self.http.call("POST", "products", json={"product": data})

    def update_product(self, sku: str, data: dict) -> dict:
        """PUT /products/{sku} — update a product."""
        return self.http.call("PUT", f"products/{quote(sku, safe='')}", json={"product": data})

    def delete_product(self, sku: str) -> bool:
        """DELETE /products/{sku} — delete a product."""
        result = self.http.call("DELETE", f"products/{quote(sku, safe='')}")
        return result is True or result == "true"

    # ── Stock ──

    def get_stock_item(self, sku: str) -> dict:
        """GET /stockItems/{sku} — get stock info."""
        return self.http.call("GET", f"stockItems/{quote(sku, safe='')}")

    def update_stock(self, sku: str, item_id: int, data: dict) -> dict:
        """PUT /products/{sku}/stockItems/{itemId} — update stock."""
        return self.http.call("PUT", f"products/{quote(sku, safe='')}/stockItems/{item_id}", json={"stockItem": data})

    # ── Orders ──

    def get_orders(self, page: int = 1, page_size: int = 100, filters: list[dict] | None = None) -> dict:
        """GET /orders — list orders with searchCriteria."""
        params = self._search_params(page=page, page_size=page_size, filters=filters, sort_field="created_at", sort_dir="DESC")
        return self.http.call("GET", "orders", params=params)

    def get_order(self, order_id: int) -> dict:
        """GET /orders/{id} — fetch a single order."""
        return self.http.call("GET", f"orders/{order_id}")

    def add_order_comment(self, order_id: int, status: str, comment: str = "", notify: bool = False) -> dict:
        """POST /orders/{id}/comments — add a comment and optionally change status."""
        payload = {
            "statusHistory": {
                "comment": comment,
                "status": status,
                "is_customer_notified": 1 if notify else 0,
            }
        }
        return self.http.call("POST", f"orders/{order_id}/comments", json=payload)

    # ── Categories ──

    def get_categories(self, root_id: int | None = None) -> dict:
        """GET /categories — fetch the category tree."""
        if root_id:
            return self.http.call("GET", f"categories/{root_id}")
        return self.http.call("GET", "categories")

    def get_category_list(self, page: int = 1, page_size: int = 100) -> dict:
        """GET /categories/list — flat list of categories with searchCriteria."""
        params = self._search_params(page=page, page_size=page_size, sort_field="entity_id")
        return self.http.call("GET", "categories/list", params=params)

    def create_category(self, data: dict) -> dict:
        """POST /categories — create a category."""
        return self.http.call("POST", "categories", json={"category": data})

    # ── Attributes ──

    def get_attributes(self, page: int = 1, page_size: int = 100) -> dict:
        """GET /products/attributes — list attribute definitions."""
        params = self._search_params(page=page, page_size=page_size, sort_field="attribute_id")
        return self.http.call("GET", "products/attributes", params=params)

    def get_attribute(self, attribute_code: str) -> dict:
        """GET /products/attributes/{code}"""
        return self.http.call("GET", f"products/attributes/{quote(attribute_code, safe='')}")

    def create_attribute(self, data: dict) -> dict:
        """POST /products/attributes"""
        return self.http.call("POST", "products/attributes", json={"attribute": data})

    def get_attribute_options(self, attribute_code: str) -> list[dict]:
        """GET /products/attributes/{code}/options"""
        result = self.http.call("GET", f"products/attributes/{quote(attribute_code, safe='')}/options")
        return result if isinstance(result, list) else []

    def add_attribute_option(self, attribute_code: str, data: dict) -> str:
        """POST /products/attributes/{code}/options"""
        return self.http.call("POST", f"products/attributes/{quote(attribute_code, safe='')}/options", json={"option": data})

    # ── Configurable Products (variants) ──

    def get_configurable_children(self, sku: str) -> list[dict]:
        """GET /configurable-products/{sku}/children"""
        result = self.http.call("GET", f"configurable-products/{quote(sku, safe='')}/children")
        return result if isinstance(result, list) else []

    def link_configurable_child(self, parent_sku: str, child_sku: str) -> bool:
        """POST /configurable-products/{sku}/child"""
        return self.http.call("POST", f"configurable-products/{quote(parent_sku, safe='')}/child", json={"childSku": child_sku})

    def remove_configurable_child(self, parent_sku: str, child_sku: str) -> bool:
        """DELETE /configurable-products/{sku}/children/{childSku}"""
        return self.http.call("DELETE", f"configurable-products/{quote(parent_sku, safe='')}/children/{quote(child_sku, safe='')}")

    # ── Product Links (related/upsell/crosssell) ──

    def get_product_links(self, sku: str, link_type: str = "related") -> list[dict]:
        """GET /products/{sku}/links/{type}"""
        result = self.http.call("GET", f"products/{quote(sku, safe='')}/links/{link_type}")
        return result if isinstance(result, list) else []

    def set_product_links(self, sku: str, links: list[dict]) -> bool:
        """POST /products/{sku}/links"""
        return self.http.call("POST", f"products/{quote(sku, safe='')}/links", json={"items": links})

    # ── Product Media ──

    def add_product_media(self, sku: str, data: dict) -> str:
        """POST /products/{sku}/media — add an image to a product. Returns media entry ID."""
        return self.http.call("POST", f"products/{quote(sku, safe='')}/media", json={"entry": data})
