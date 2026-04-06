"""
Gomag API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class GomagApiClient:
    """
    Low-level Gomag API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.

    Gomag POST endpoints expect a form-encoded ``data`` field containing
    a JSON string.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def _post(self, path: str, payload: Any, **kwargs) -> dict:
        """POST with Gomag's form-encoded ``data`` convention."""
        return self.http.call("POST", path, data={"data": json.dumps(payload)}, **kwargs)

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

    def create_product(self, payload: list[dict], **kwargs) -> dict:
        return self._post("product/write/json", payload, **kwargs)

    def update_product(self, payload: list[dict], **kwargs) -> dict:
        return self._post("product/patch/json", payload, **kwargs)

    def update_product_inventory(self, payload: list[dict], **kwargs) -> dict:
        return self._post("product/inventory/json", payload, **kwargs)

    def delete_product(self, payload: list[dict], **kwargs) -> dict:
        return self._post("product/delete/json", payload, **kwargs)

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

    def create_order(self, payload: dict, **kwargs) -> dict:
        return self._post("order/add/json", payload, **kwargs)

    def add_order_note(self, order_id: int, note: str, is_public: bool = False, **kwargs) -> dict:
        payload: dict[str, Any] = {"order_id": order_id, "note": note}
        if is_public:
            payload["is_public"] = True
        return self._post("order/note/add/json", payload, **kwargs)

    def add_order_file(self, order_id: int, url: str, name: str = "", **kwargs) -> dict:
        payload: dict[str, Any] = {"order_id": order_id, "url": url}
        if name:
            payload["name"] = name
        return self._post("order/file/add/json", payload, **kwargs)

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

    def create_category(self, payload: list[dict], **kwargs) -> dict:
        return self._post("category/write/json", payload, **kwargs)

    def update_category(self, payload: list[dict], **kwargs) -> dict:
        return self._post("category/patch/json", payload, **kwargs)

    def delete_category(self, payload: list[dict], **kwargs) -> dict:
        return self._post("category/delete/json", payload, **kwargs)

    # ── AWB / Shipping ──

    def get_carriers(self, **kwargs) -> dict:
        return self.http.call("GET", "awb/carrier/read/json", **kwargs)

    def get_awbs(
        self,
        order_id: int | None = None,
        awb_number: str | None = None,
        carrier_id: int | None = None,
        page: int = 1,
        limit: int = 100,
        **kwargs,
    ) -> dict:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if order_id is not None:
            params["order_id"] = order_id
        if awb_number is not None:
            params["awb_number"] = awb_number
        if carrier_id is not None:
            params["carrier_id"] = carrier_id
        return self.http.call("GET", "awb/read/json", params=params, **kwargs)

    def create_awb(self, payload: dict, **kwargs) -> dict:
        return self._post("awb/add/json", payload, **kwargs)

    def generate_awb(self, payload: dict, **kwargs) -> dict:
        return self._post("awb/generate/json", payload, **kwargs)

    def delete_awb(self, awb_id: int, **kwargs) -> dict:
        return self._post("awb/delete/json", {"awb_id": awb_id}, **kwargs)

    def print_awb(self, awb_id: int, **kwargs) -> dict:
        return self._post("awb/print/json", {"awb_id": awb_id}, **kwargs)

    def update_awb_status(self, awb_id: int, status: str, update_order_status: bool = False, **kwargs) -> dict:
        payload: dict[str, Any] = {"awb_id": awb_id, "status": status}
        if update_order_status:
            payload["update_order_status"] = True
        return self._post("awb/status/update/json", payload, **kwargs)

    # ── Invoices ──

    def create_invoice(self, payload: dict, **kwargs) -> dict:
        return self._post("invoice/add/json", payload, **kwargs)

    def generate_invoice(self, order_id: int, series: str | None = None, **kwargs) -> dict:
        payload: dict[str, Any] = {"orderId": order_id}
        if series:
            payload["series"] = series
        return self._post("invoice/generate/json", payload, **kwargs)

    def cancel_invoice(self, invoice_id: int, **kwargs) -> dict:
        return self._post("invoice/cancel/json", {"invoice_id": invoice_id}, **kwargs)

    # ── Attributes ──

    def get_attributes(self, attribute_id: int | None = None, page: int = 1, limit: int = 100, **kwargs) -> dict:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if attribute_id is not None:
            params["id"] = attribute_id
        return self.http.call("GET", "attribute/read/json", params=params, **kwargs)

    def create_attribute(self, payload: list[dict], **kwargs) -> dict:
        return self._post("attribute/write/json", payload, **kwargs)

    def update_attribute(self, payload: list[dict], **kwargs) -> dict:
        return self._post("attribute/patch/json", payload, **kwargs)

    # ── Customers ──

    def get_customers(
        self,
        customer_id: int | None = None,
        email: str | None = None,
        phone: str | None = None,
        updated: str | None = None,
        page: int = 1,
        limit: int = 100,
        **kwargs,
    ) -> dict:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if customer_id is not None:
            params["id"] = customer_id
        if email is not None:
            params["email"] = email
        if phone is not None:
            params["phone"] = phone
        if updated is not None:
            params["updated"] = updated
        return self.http.call("GET", "customer/read/json", params=params, **kwargs)

    # ── Payment Methods ──

    def get_payment_methods(self, **kwargs) -> dict:
        return self.http.call("GET", "payment/read/json", **kwargs)
