"""
WooCommerce API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class WooCommerceApiClient:
    """
    Low-level WooCommerce API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, consumer_key: str = "", consumer_secret: str = "", use_query_auth: bool = False):
        self.http = http_client
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._use_query_auth = use_query_auth

    def _call(self, method: str, path: str, **kwargs):
        """Make an API call, adding query-string auth if enabled."""
        if self._use_query_auth and self._consumer_key:
            params = kwargs.pop("params", {})
            if not isinstance(params, dict):
                params = {}
            params["consumer_key"] = self._consumer_key
            params["consumer_secret"] = self._consumer_secret
            kwargs["params"] = params
        return self.http.call(method, path, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        try:
            self.get_products(per_page=1)
            return True
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        page: int = 1,
        per_page: int = 100,
        status: str | None = None,
        after: str | None = None,
        order_id: str | None = None,
        **kwargs,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "orderby": "date",
            "order": "desc",
        }
        if status:
            params["status"] = status
        if after:
            params["after"] = after
        if order_id:
            params["include"] = order_id

        return self._call("GET", "orders", params=params, **kwargs)

    def get_order(self, order_id: str, **kwargs) -> dict:
        return self._call("GET", f"orders/{order_id}", **kwargs)

    def update_order(self, order_id: str, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"orders/{order_id}", json=data, **kwargs)

    # ── Products ──

    def get_products(self, page: int = 1, per_page: int = 100, **kwargs) -> list[dict]:
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "orderby": "date",
            "order": "desc",
        }
        extra_params = kwargs.pop("params", {})
        params.update(extra_params)
        return self._call("GET", "products", params=params, **kwargs)

    def get_product(self, product_id: str, **kwargs) -> dict:
        return self._call("GET", f"products/{product_id}", **kwargs)

    def create_product(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "products", json=data, **kwargs)

    def delete_product(self, product_id: str, **kwargs) -> dict:
        return self._call("DELETE", f"products/{product_id}", params={"force": "true"}, **kwargs)

    def update_product(self, product_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/{product_id}", json=data, **kwargs)

    def batch_update_products(self, updates: list[dict], **kwargs) -> dict:
        return self._call("POST", "products/batch", json={"update": updates}, **kwargs)

    # ── Categories ──

    def get_categories(self, page: int = 1, per_page: int = 100, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"page": page, "per_page": per_page, "orderby": "id", "order": "asc"}
        return self._call("GET", "products/categories", params=params, **kwargs)

    def create_category(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "products/categories", json=data, **kwargs)

    # ── Product Attributes ──

    def get_attributes(self, **kwargs) -> list[dict]:
        return self._call("GET", "products/attributes", params={"per_page": 100}, **kwargs)

    def get_attribute(self, attribute_id: int, **kwargs) -> dict:
        return self._call("GET", f"products/attributes/{attribute_id}", **kwargs)

    def create_attribute(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "products/attributes", json=data, **kwargs)

    def update_attribute(self, attribute_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/attributes/{attribute_id}", json=data, **kwargs)

    def delete_attribute(self, attribute_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"products/attributes/{attribute_id}", params={"force": "true"}, **kwargs)

    # ── Attribute Terms ──

    def get_attribute_terms(self, attribute_id: int, **kwargs) -> list[dict]:
        return self._call("GET", f"products/attributes/{attribute_id}/terms", params={"per_page": 100}, **kwargs)

    def create_attribute_term(self, attribute_id: int, data: dict, **kwargs) -> dict:
        return self._call("POST", f"products/attributes/{attribute_id}/terms", json=data, **kwargs)

    # ── Variations ──

    def get_variations(self, product_id: int, page: int = 1, per_page: int = 100, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        return self._call("GET", f"products/{product_id}/variations", params=params, **kwargs)

    def get_variation(self, product_id: int, variation_id: int, **kwargs) -> dict:
        return self._call("GET", f"products/{product_id}/variations/{variation_id}", **kwargs)

    def create_variation(self, product_id: int, data: dict, **kwargs) -> dict:
        return self._call("POST", f"products/{product_id}/variations", json=data, **kwargs)

    def update_variation(self, product_id: int, variation_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/{product_id}/variations/{variation_id}", json=data, **kwargs)

    def delete_variation(self, product_id: int, variation_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"products/{product_id}/variations/{variation_id}", params={"force": "true"}, **kwargs)

    # ── Webhooks ──

    def get_webhooks(self, **kwargs) -> list[dict]:
        return self._call("GET", "webhooks", **kwargs)

    def create_webhook(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "webhooks", json=data, **kwargs)

    def delete_webhook(self, webhook_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"webhooks/{webhook_id}", params={"force": "true"}, **kwargs)
