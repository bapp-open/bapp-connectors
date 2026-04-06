"""
Okazii API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class OkaziiApiClient:
    """
    Low-level Okazii API client.

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

    def get_countries(self) -> dict | list | str:
        """List countries — used as a lightweight auth check."""
        return self._call("GET", "countries")

    def test_auth(self) -> bool:
        try:
            result = self.get_countries()
            return bool(result)
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        created_after: datetime.datetime | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        params: dict[str, Any] = {}
        if created_after:
            today = datetime.date.today()
            params["date_from"] = created_after.strftime("%Y-%m-%d")
            params["date_to"] = today.strftime("%Y-%m-%d")
        extra_params = kwargs.pop("params", {})
        params.update(extra_params)
        result = self._call("GET", "export_orders", params=params, **kwargs)
        if isinstance(result, dict):
            return result.get("hydra:member", [])
        return []

    def get_order(self, order_id: int | str) -> dict:
        result = self._call("GET", f"export_orders/{order_id}")
        if isinstance(result, dict):
            return result
        return {}

    # ── Couriers ──

    def get_order_courier(self, order_id: int | str) -> dict | str:
        return self._call("GET", f"order_awbs/{order_id}")

    def get_couriers(self) -> list[dict]:
        result = self._call("GET", "bid_awb_couriers")
        if isinstance(result, dict):
            return result.get("hydra:member", [])
        return []

    # ── Invoice ──

    def get_order_invoices(self, order_id: int | str) -> dict | str:
        return self._call("GET", f"export_order_invoices/{order_id}")

    def attach_invoice(self, order_id: int | str, file_name: str, file_content: bytes) -> dict | str:
        """Attach an invoice PDF file to an order."""
        # For file uploads, we bypass the JSON content-type
        files = {"file": (file_name, file_content, "application/pdf")}
        return self._call(
            "POST",
            f"export_order_invoices/{order_id}",
            files=files,
            headers={"User-Agent": "Python 3 - BAPP Agent"},
        )

    def attach_invoice_url(self, order_id: int | str, invoice_url: str) -> dict | str:
        """Attach an invoice URL to an order (POST with JSON body)."""
        return self._call(
            "POST",
            f"export_order_invoices/{order_id}",
            json={"invoice_url": invoice_url},
        )

    # ── Location ──

    def get_cities(self, **kwargs) -> list[dict]:
        """List cities with courier availability."""
        result = self._call("GET", "cities", **kwargs)
        if isinstance(result, dict):
            return result.get("hydra:member", [])
        return []

    def get_counties(self, **kwargs) -> list[dict]:
        """List counties."""
        result = self._call("GET", "counties", **kwargs)
        if isinstance(result, dict):
            return result.get("hydra:member", [])
        return []

    # ── GDL AWB (Okazii-managed shipping) ──

    def get_gdl_awb(self, awb_id: int | str) -> dict:
        """Get GDL AWB details."""
        result = self._call("GET", f"order_awb_gdls/{awb_id}")
        return result if isinstance(result, dict) else {}

    def create_gdl_awb(
        self,
        order_id: int | str,
        weight: float,
        width: float,
        length: float,
        height: float,
        commercial_discount: float = 0,
    ) -> dict | str:
        """Create a GDL AWB (Okazii-managed courier shipping)."""
        return self._call(
            "POST",
            "order_awb_gdls",
            json={
                "orderid": str(order_id),
                "weight": weight,
                "width": width,
                "length": length,
                "height": height,
                "commercialDiscount": commercial_discount,
            },
        )

    def get_gdl_awb_pdf(self, awb_id: int | str) -> bytes:
        """Download GDL AWB PDF."""
        response = self.http.call("GET", f"order_awb_gdl_pdfs/{awb_id}", headers=self._extra_headers, direct_response=True)
        if hasattr(response, "content"):
            return response.content
        return b""

    # ── AWB (update) ──

    def update_awb(self, order_id: int | str, awb_data: dict) -> dict | str:
        """Update AWB tracking info for an order."""
        return self._call("PUT", f"order_awbs/{order_id}", json=awb_data)

    # ── Seller Pickup Address ──

    def get_seller_pickup_address(self, address_id: int | str) -> dict:
        """Get seller's pickup address."""
        result = self._call("GET", f"seller_pickup_addresses/{address_id}")
        return result if isinstance(result, dict) else {}

    def update_seller_pickup_address(self, address_id: int | str, address_data: dict) -> dict | str:
        """Update seller's pickup address."""
        return self._call("PUT", f"seller_pickup_addresses/{address_id}", json=address_data)
