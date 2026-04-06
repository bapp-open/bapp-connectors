"""
eMAG API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.shop.emag.errors import EmagError, EmagIPWhitelistError
from bapp_connectors.providers.shop.emag.models import EmagApiResponse

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


def _json_encode(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class EmagApiClient:
    """
    Low-level eMAG API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client
        self._extra_headers = {
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        headers = dict(self._extra_headers)
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    def _post_read(self, endpoint: str, payload: dict | None = None) -> EmagApiResponse:
        """
        eMAG uses POST for most read operations with filter payloads.
        Returns a parsed EmagApiResponse.
        """
        data = _json_encode(payload or {})
        raw = self._call("POST", endpoint, data=data)
        return self._parse_response(raw)

    def _parse_response(self, raw: dict | list | str) -> EmagApiResponse:
        """Parse raw API response into an EmagApiResponse model."""
        if isinstance(raw, dict):
            resp = EmagApiResponse(**raw)
            if resp.is_error:
                msg = "; ".join(resp.messages) if resp.messages else "Unknown eMAG API error"
                raise EmagError(msg)
            return resp
        raise EmagError(f"Unexpected response type: {type(raw).__name__}")

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test authentication by fetching first page of categories.

        Raises EmagIPWhitelistError if the server IP is not whitelisted,
        so the caller can show a meaningful error message.
        """
        try:
            self.get_categories(page=1)
            return True
        except EmagIPWhitelistError:
            raise  # Let IP whitelist errors bubble up for actionable feedback
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        page: int = 1,
        per_page: int = 100,
        status: int | list[int] | None = None,
        order_id: int | None = None,
        created_after: str | None = None,
        **kwargs,
    ) -> EmagApiResponse:
        """Fetch orders with optional filters.

        Args:
            status: Single status int or list of statuses (e.g. [0, 1, 2]).
            created_after: Date string in '%Y-%m-%d %H:%M' format.
        """
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
            "is_complete": 1,
        }
        if status is not None:
            payload["status"] = status
        if order_id is not None:
            payload["id"] = order_id
        if created_after is not None:
            payload["createdAfter"] = created_after
        return self._post_read("order/read", payload)

    def get_order(self, order_id: int) -> dict:
        """Fetch a single order by its eMAG ID."""
        resp = self.get_orders(order_id=order_id)
        return resp.results[0] if resp.results else {}

    def order_acknowledge(self, order_id: int, max_retries: int = 3) -> EmagApiResponse:
        """Acknowledge an order (mark as being prepared / status 2).

        Retries on "Resource locked for processing" and silently succeeds
        if the order is already in progress.
        """
        import time

        for attempt in range(max_retries):
            try:
                return self.update_order_status(order_id, status=2)
            except EmagError as e:
                msg = str(e).lower()
                if "already in progress" in msg:
                    # Order was already acknowledged — treat as success
                    return EmagApiResponse(is_error=False, results=[])
                if "locked for processing" in msg and attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise
        raise EmagError(f"Failed to acknowledge order {order_id} after {max_retries} retries")

    def update_order_status(self, order_id: int, status: int) -> EmagApiResponse:
        """Update an order's status on eMAG."""
        data = _json_encode([{"id": order_id, "status": status}])
        raw = self._call("POST", "order/save", data=data)
        return self._parse_response(raw)

    # ── Products ──

    def get_products(
        self,
        page: int = 1,
        per_page: int = 100,
        **kwargs,
    ) -> EmagApiResponse:
        """Fetch product offers."""
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        extra_params = kwargs.pop("params", {})
        payload.update(extra_params)
        return self._post_read("product_offer/read", payload)

    def update_product(self, product_data: list[dict]) -> EmagApiResponse:
        """Update one or more product offers via product_offer/save."""
        data = _json_encode(product_data)
        raw = self._call("POST", "product_offer/save", data=data)
        return self._parse_response(raw)

    def update_offer(self, offer_data: list[dict]) -> EmagApiResponse:
        """Update one or more offers via offer/save (newer eMAG API)."""
        data = _json_encode(offer_data)
        raw = self._call("POST", "offer/save", data=data)
        return self._parse_response(raw)

    def update_offer_stock(self, product_id: int, quantity: int) -> EmagApiResponse:
        """Update stock via dedicated PATCH endpoint (lighter than product_offer/save)."""
        data = _json_encode({"stock": quantity})
        raw = self._call("PATCH", f"offer_stock/{product_id}", data=data)
        return self._parse_response(raw)

    # ── Categories ──

    def get_categories(self, page: int = 1, per_page: int = 100) -> EmagApiResponse:
        """Fetch categories."""
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        return self._post_read("category/read", payload)

    def get_product_count(self) -> EmagApiResponse:
        """Get total product offer count."""
        return self._post_read("product_offer/count")

    # ── Couriers ──

    def get_couriers(self) -> EmagApiResponse:
        """Fetch available courier accounts."""
        return self._post_read("courier_accounts/read")

    # ── VAT ──

    def get_vat_list(self) -> EmagApiResponse:
        """Fetch VAT rates."""
        return self._post_read("vat/read")

    # ── Locality ──

    def get_locality(self, region: str, name: str, country: str = "RO") -> EmagApiResponse:
        """Look up a locality by region and name."""
        payload: dict[str, Any] = {
            "region2": region,
            "name": name,
            "county_name": country,
        }
        return self._post_read("locality/read", payload)

    # ── AWB / Shipping ──

    def generate_awb(self, awb_data: dict) -> EmagApiResponse:
        """Generate AWB via eMAG's awb/save endpoint."""
        data = _json_encode(awb_data)
        raw = self._call("POST", "awb/save", data=data, timeout=60)
        return self._parse_response(raw)

    def read_awb(
        self,
        emag_id: int | None = None,
        reservation_id: int | None = None,
    ) -> EmagApiResponse:
        """Read AWB details."""
        payload: dict[str, Any] = {}
        if emag_id is not None:
            payload["emag_id"] = emag_id
        if reservation_id is not None:
            payload["reservation_id"] = reservation_id
        return self._post_read("awb/read", payload)

    def read_awb_pdf(self, order_id: int, pdf_format: str = "A4", **kwargs) -> bytes:
        """
        Download AWB PDF for an order.
        eMAG returns the PDF content directly from the awb/read_pdf endpoint.
        """
        payload: dict[str, Any] = {"order_id": order_id}
        data = _json_encode(payload)
        response = self.http.call(
            "POST",
            f"awb/read_pdf?awb_format={pdf_format}",
            data=data,
            headers=dict(self._extra_headers),
            direct_response=True,
            **kwargs,
        )
        if hasattr(response, "content"):
            return response.content
        return b""

    # ── Invoice API ──
    # Invoice endpoints return {total_results, invoices} instead of the standard
    # {isError, results} wrapper, so they use _call directly.

    def get_invoice_categories(self) -> dict:
        """Fetch invoice categories (e.g. FC=Commission)."""
        data = _json_encode({})
        return self._call("POST", "invoice/categories", data=data)

    def get_invoices(
        self,
        category: str | None = None,
        number: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Fetch eMAG-to-seller invoices (commissions, settlements).

        Args:
            category: Invoice category code (e.g. "FC").
            number: Invoice series+number filter.
            date_start: Start date (YYYY-MM-DD).
            date_end: End date (YYYY-MM-DD).
        """
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        if category:
            payload["category"] = category
        if number:
            payload["number"] = number
        if date_start:
            payload["date_start"] = date_start
        if date_end:
            payload["date_end"] = date_end
        data = _json_encode(payload)
        return self._call("POST", "invoice/read", data=data)

    def get_customer_invoices(
        self,
        category: str | None = None,
        order_id: int | None = None,
        number: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Fetch seller-to-customer invoices.

        Args:
            category: "normal" or "storno".
            order_id: Filter by order ID.
            number: Invoice series+number filter.
            date_start: Start date (YYYY-MM-DD).
            date_end: End date (YYYY-MM-DD).
        """
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        if category:
            payload["category"] = category
        if order_id is not None:
            payload["order_id"] = order_id
        if number:
            payload["number"] = number
        if date_start:
            payload["date_start"] = date_start
        if date_end:
            payload["date_end"] = date_end
        data = _json_encode(payload)
        return self._call("POST", "customer-invoice/read", data=data)

    # ── Order Attachments ──

    def order_attachment_save(
        self,
        order_id: int,
        attachment_url: str,
        attachment_name: str = "",
        attachment_type: int = 1,
    ) -> EmagApiResponse:
        """
        Attach a document (invoice) to an order.

        attachment_type: 1=invoice, 3=warranty, 4=user manual, 8=user guide,
                         10=AWB, 11=proforma
        """
        item: dict[str, Any] = {
            "order_id": order_id,
            "url": attachment_url,
            "type": attachment_type,
            "force_download": 1,
        }
        if attachment_name:
            item["name"] = attachment_name
        payload = [item]
        data = _json_encode(payload)
        raw = self._call("POST", "order/attachments/save", data=data)
        return self._parse_response(raw)
