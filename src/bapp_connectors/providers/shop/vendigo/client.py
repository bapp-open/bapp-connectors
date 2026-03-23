"""
Vendigo API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.http import ResilientHttpClient


class VendigoApiClient:
    """
    Low-level Vendigo API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

        self._extra_headers = {
            "User-Agent": "Python 3 - BAPP Agent",
            "Content-Type": "application/json;charset=utf-8",
        }

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        headers = dict(self._extra_headers)
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def get_groups(self) -> list:
        """List product groups — used as a lightweight auth check."""
        result = self._call("GET", "groups/list")
        if isinstance(result, dict):
            return result.get("groups", [])
        return []

    def test_auth(self) -> bool:
        try:
            self.get_groups()
            return True
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        created_after: datetime | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if created_after:
            params["date_from"] = created_after.strftime("%Y-%m-%d")
        extra_params = kwargs.pop("params", {})
        params.update(extra_params)
        result = self._call("GET", "orders/list", params=params, **kwargs)
        if isinstance(result, dict):
            return result.get("orders", [])
        return []

    def get_order(self, order_id: int | str) -> dict:
        result = self._call("GET", f"orders/{order_id}")
        if isinstance(result, dict):
            return result.get("order", {})
        return {}

    def set_order_status(self, order_id: int | str, status: str, **kwargs: Any) -> dict | str:
        return self._call(
            "POST",
            "orders/set_status",
            json={"status": status, "ids": [order_id]},
            **kwargs,
        )

    def order_acknowledge(self, order_id: int | str) -> dict | str:
        """Acknowledge the order to the marketplace."""
        return self.set_order_status(order_id=order_id, status="received", timeout=30)

    # ── Invoice ──

    def order_attachment(self, order_id: int | str, invoice_url: str) -> dict | str:
        return self._call(
            "POST",
            f"orders/{order_id}/attach_receipt",
            json={"receipt_url": invoice_url},
        )

    # ── Products ──

    def get_products(self) -> list[dict]:
        result = self._call("GET", "products/list")
        if isinstance(result, dict):
            return result.get("products", [])
        return []

    def get_product_by_external_id(self, external_id: int | str) -> dict:
        result = self._call("GET", f"products/by_external_id/{external_id}")
        if isinstance(result, dict):
            return result.get("product", {})
        return {}

    # ── Other ──

    def get_payment_options(self) -> list[dict]:
        result = self._call("GET", "payment_options/list")
        if isinstance(result, dict):
            return result.get("payment_options", [])
        return []

    def get_delivery_options(self) -> list[dict]:
        result = self._call("GET", "delivery_options/list")
        if isinstance(result, dict):
            return result.get("delivery_options", [])
        return []
