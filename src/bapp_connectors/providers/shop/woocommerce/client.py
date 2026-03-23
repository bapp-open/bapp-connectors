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

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

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

        return self.http.call("GET", "orders", params=params, **kwargs)

    def get_order(self, order_id: str, **kwargs) -> dict:
        return self.http.call("GET", f"orders/{order_id}", **kwargs)

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
        return self.http.call("GET", "products", params=params, **kwargs)

    def create_product(self, data: dict, **kwargs) -> dict:
        return self.http.call("POST", "products", json=data, **kwargs)

    def update_product(self, product_id: int, data: dict, **kwargs) -> dict:
        return self.http.call("PUT", f"products/{product_id}", json=data, **kwargs)

    def batch_update_products(self, updates: list[dict], **kwargs) -> dict:
        return self.http.call("POST", "products/batch", json={"update": updates}, **kwargs)

    # ── Webhooks ──

    def get_webhooks(self, **kwargs) -> list[dict]:
        return self.http.call("GET", "webhooks", **kwargs)

    def create_webhook(self, data: dict, **kwargs) -> dict:
        return self.http.call("POST", "webhooks", json=data, **kwargs)

    def delete_webhook(self, webhook_id: int, **kwargs) -> dict:
        return self.http.call("DELETE", f"webhooks/{webhook_id}", params={"force": "true"}, **kwargs)
