"""
Gomag API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class GomagApiClient:
    """
    Low-level Gomag API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        try:
            self.get_products(limit=1)
            return True
        except Exception:
            return False

    # ── Products ──

    def get_products(self, page: int = 1, limit: int = 100, **kwargs) -> dict:
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        extra_params = kwargs.pop("params", {})
        params.update(extra_params)
        return self.http.call("GET", "product/read/json", params=params, **kwargs)

    # ── Orders ──

    def get_orders(self, page: int = 1, limit: int = 100, **kwargs) -> dict:
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        extra_params = kwargs.pop("params", {})
        params.update(extra_params)
        return self.http.call("GET", "order/read/json", params=params, **kwargs)

    def get_order(self, order_id: str, **kwargs) -> dict:
        params: dict[str, Any] = {"order_id": order_id}
        return self.http.call("GET", "order/read/json", params=params, **kwargs)

    def update_order_status(self, order_id: str, status: str, **kwargs) -> dict:
        params: dict[str, Any] = {
            "order_id": order_id,
            "status": status,
        }
        return self.http.call("GET", "order/status/json", params=params, **kwargs)

    # ── Order Statuses ──

    def get_order_statuses(self, **kwargs) -> dict:
        return self.http.call("GET", "order/status/read/json", **kwargs)

    # ── Categories ──

    def get_categories(self, page: int = 1, limit: int = 100, **kwargs) -> dict:
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
        }
        return self.http.call("GET", "category/read/json", params=params, **kwargs)
