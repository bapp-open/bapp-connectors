"""
WooCommerce API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bapp_connectors.core.ai import ai_method, drop_method_override

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
        """Make an API call, adding query-string auth if enabled.

        WordPress honours `?_method=DELETE` on a GET, so a read never carries it.
        """
        if method == "GET" and "params" in kwargs:
            kwargs["params"] = drop_method_override(kwargs["params"], "_method")
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

    @ai_method(
        "read",
        "Orders, newest first, one page per call (page, per_page up to 100); params adds WooCommerce list filters.",
        extra={
            "params": "flat",
        },
    )
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

        params.update(kwargs.pop("params", {}))
        return self._call("GET", "orders", params=params, **kwargs)

    @ai_method("read", "One order by its WooCommerce id.")
    def get_order(self, order_id: int, **kwargs) -> dict:
        return self._call("GET", f"orders/{order_id}", **kwargs)

    @ai_method("write", "Update an order (status, notes, fields) with the given data.")
    def update_order(self, order_id: str, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"orders/{order_id}", json=data, **kwargs)

    @ai_method("read", "Every registered order status with its order count, in one call.")
    def get_order_status_totals(self, **kwargs) -> list[dict]:
        """Every registered order status, `[{slug, name, total}]`.

        WooCommerce has no endpoint that simply lists statuses; this report is the documented
        way to read them, and it includes the ones a plugin or the merchant registered.
        """
        return self._call("GET", "reports/orders/totals", **kwargs)

    @ai_method(
        "read",
        "Refunds across all orders, one page per call (page, per_page), optionally between after and before.",
    )
    def get_refunds(self, page: int = 1, per_page: int = 100, after: str | None = None, before: str | None = None, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"page": page, "per_page": per_page, "dates_are_gmt": "true"}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._call("GET", "refunds", params=params, **kwargs)

    # ── Products ──

    @ai_method(
        "read",
        "Products, newest first, one page per call (page, per_page up to 100); params adds WooCommerce list filters.",
        extra={
            "params": "flat",
        },
    )
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

    @ai_method("read", "One product by its WooCommerce id.")
    def get_product(self, product_id: int, **kwargs) -> dict:
        return self._call("GET", f"products/{product_id}", **kwargs)

    # Creates are not idempotent and, with images, WordPress sideloads every photo inside the
    # request: long read timeout, never retried (a timeout may still have created the product).
    CREATE_TIMEOUT = (10, 300)

    @ai_method("write", "Create a product.")
    def create_product(self, data: dict, **kwargs) -> dict:
        kwargs.setdefault("timeout", self.CREATE_TIMEOUT)
        kwargs.setdefault("retry", False)
        return self._call("POST", "products", json=data, **kwargs)

    @ai_method("write", "Delete a product permanently.")
    def delete_product(self, product_id: str, **kwargs) -> dict:
        return self._call("DELETE", f"products/{product_id}", params={"force": "true"}, **kwargs)

    @ai_method("write", "Update a product with the given data.")
    def update_product(self, product_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/{product_id}", json=data, **kwargs)

    @ai_method("write", "Update several products in one products/batch call.")
    def batch_update_products(self, updates: list[dict], **kwargs) -> dict:
        kwargs.setdefault("timeout", self.CREATE_TIMEOUT)
        return self._call("POST", "products/batch", json={"update": updates}, **kwargs)

    @ai_method("write", "Create, update or delete products in one products/batch call.")
    def batch_products(self, payload: dict, **kwargs) -> dict:
        """Raw POST products/batch with any of create/update/delete lists (long timeout, no retry)."""
        kwargs.setdefault("timeout", self.CREATE_TIMEOUT)
        kwargs.setdefault("retry", False)
        return self._call("POST", "products/batch", json=payload, **kwargs)

    # ── Categories ──

    @ai_method("read", "Product categories, one page per call (page, per_page up to 100).")
    def get_categories(self, page: int = 1, per_page: int = 100, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"page": page, "per_page": per_page, "orderby": "id", "order": "asc"}
        return self._call("GET", "products/categories", params=params, **kwargs)

    @ai_method("write", "Create a product category.")
    def create_category(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "products/categories", json=data, **kwargs)

    @ai_method("write", "Update a product category.")
    def update_category(self, category_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/categories/{category_id}", json=data, **kwargs)

    # ── Product Attributes ──

    @ai_method("read", "The global product attributes (up to 100), in one call.")
    def get_attributes(self, **kwargs) -> list[dict]:
        return self._call("GET", "products/attributes", params={"per_page": 100}, **kwargs)

    @ai_method("read", "One global product attribute by id.")
    def get_attribute(self, attribute_id: int, **kwargs) -> dict:
        return self._call("GET", f"products/attributes/{attribute_id}", **kwargs)

    @ai_method("write", "Create a global product attribute.")
    def create_attribute(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "products/attributes", json=data, **kwargs)

    @ai_method("write", "Update a global product attribute.")
    def update_attribute(self, attribute_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/attributes/{attribute_id}", json=data, **kwargs)

    @ai_method("write", "Delete a global product attribute permanently.")
    def delete_attribute(self, attribute_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"products/attributes/{attribute_id}", params={"force": "true"}, **kwargs)

    # ── Attribute Terms ──

    @ai_method("read", "The terms of one global attribute (up to 100), in one call.")
    def get_attribute_terms(self, attribute_id: int, **kwargs) -> list[dict]:
        return self._call("GET", f"products/attributes/{attribute_id}/terms", params={"per_page": 100}, **kwargs)

    @ai_method("write", "Add a term to a global attribute.")
    def create_attribute_term(self, attribute_id: int, data: dict, **kwargs) -> dict:
        return self._call("POST", f"products/attributes/{attribute_id}/terms", json=data, **kwargs)

    # ── Variations ──

    @ai_method("read", "The variations of one variable product, one page per call (page, per_page).")
    def get_variations(self, product_id: int, page: int = 1, per_page: int = 100, **kwargs) -> list[dict]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        return self._call("GET", f"products/{product_id}/variations", params=params, **kwargs)

    @ai_method("read", "One variation of a variable product.")
    def get_variation(self, product_id: int, variation_id: int, **kwargs) -> dict:
        return self._call("GET", f"products/{product_id}/variations/{variation_id}", **kwargs)

    @ai_method("write", "Create a variation on a variable product.")
    def create_variation(self, product_id: int, data: dict, **kwargs) -> dict:
        return self._call("POST", f"products/{product_id}/variations", json=data, **kwargs)

    @ai_method("write", "Update a variation of a variable product.")
    def update_variation(self, product_id: int, variation_id: int, data: dict, **kwargs) -> dict:
        return self._call("PUT", f"products/{product_id}/variations/{variation_id}", json=data, **kwargs)

    @ai_method("write", "Delete a variation permanently.")
    def delete_variation(self, product_id: int, variation_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"products/{product_id}/variations/{variation_id}", params={"force": "true"}, **kwargs)

    # ── Store settings / taxes ──

    def get_settings_group(self, group_id: str) -> list[dict]:
        return self._call("GET", f"settings/{group_id}")

    @ai_method("read", "The shop's tax rates (up to 100), in one call.")
    def get_taxes(self, **kwargs) -> list[dict]:
        return self._call("GET", "taxes", params={"per_page": 100, **kwargs})

    # ── Webhooks ──

    def get_webhooks(self, **kwargs) -> list[dict]:
        return self._call("GET", "webhooks", **kwargs)

    def create_webhook(self, data: dict, **kwargs) -> dict:
        return self._call("POST", "webhooks", json=data, **kwargs)

    def delete_webhook(self, webhook_id: int, **kwargs) -> dict:
        return self._call("DELETE", f"webhooks/{webhook_id}", params={"force": "true"}, **kwargs)
