"""
Vendigo API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- resolved at runtime by the AI tool schema
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.ai import ai_method

if TYPE_CHECKING:
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

    @ai_method("read", "The product groups, in one call.")
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

    @ai_method(
        "read",
        "Orders (one page as Vendigo answers it), created from created_after when given; params adds Vendigo filters.",
        extra={
            "params": "flat",
        },
    )
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

    @ai_method("read", "One order by its Vendigo id.")
    def get_order(self, order_id: int | str) -> dict:
        result = self._call("GET", f"orders/{order_id}")
        if isinstance(result, dict):
            return result.get("order", {})
        return {}

    @ai_method("write", "Set an order's status on Vendigo.")
    def set_order_status(self, order_id: int | str, status: str, **kwargs: Any) -> dict | str:
        return self._call(
            "POST",
            "orders/set_status",
            json={"status": status, "ids": [order_id]},
            **kwargs,
        )

    @ai_method("write", "Acknowledge an order (sets it to received).")
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

    @ai_method("read", "All products, in one call.")
    def get_products(self) -> list[dict]:
        result = self._call("GET", "products/list")
        if isinstance(result, dict):
            return result.get("products", [])
        return []

    @ai_method("read", "One product by the seller's external id.")
    def get_product_by_external_id(self, external_id: int | str) -> dict:
        result = self._call("GET", f"products/by_external_id/{external_id}")
        if isinstance(result, dict):
            return result.get("product", {})
        return {}

    # ── Other ──

    @ai_method("read", "The payment options, in one call.")
    def get_payment_options(self) -> list[dict]:
        result = self._call("GET", "payment_options/list")
        if isinstance(result, dict):
            return result.get("payment_options", [])
        return []

    @ai_method("read", "The delivery options, in one call.")
    def get_delivery_options(self) -> list[dict]:
        result = self._call("GET", "delivery_options/list")
        if isinstance(result, dict):
            return result.get("delivery_options", [])
        return []
