"""
eMAG API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from bapp_connectors.providers.shop.emag.errors import EmagError
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
        """Test authentication by fetching first page of categories."""
        try:
            self.get_categories(page=1)
            return True
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        page: int = 1,
        per_page: int = 100,
        status: int | None = None,
        order_id: int | None = None,
        **kwargs,
    ) -> EmagApiResponse:
        """Fetch orders with optional filters."""
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        if status is not None:
            payload["status"] = status
        if order_id is not None:
            payload["id"] = order_id
        return self._post_read("order/read", payload)

    def get_order(self, order_id: int) -> dict:
        """Fetch a single order by its eMAG ID."""
        resp = self.get_orders(order_id=order_id)
        return resp.results[0] if resp.results else {}

    def order_acknowledge(self, order_id: int) -> EmagApiResponse:
        """Acknowledge an order (mark as being prepared)."""
        data = _json_encode([{"id": order_id, "status": 2}])
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
        """Update one or more product offers."""
        data = _json_encode(product_data)
        raw = self._call("POST", "product_offer/save", data=data)
        return self._parse_response(raw)

    # ── Categories ──

    def get_categories(self, page: int = 1, per_page: int = 100) -> EmagApiResponse:
        """Fetch categories."""
        payload: dict[str, Any] = {
            "currentPage": page,
            "itemsPerPage": per_page,
        }
        return self._post_read("category/read", payload)

    # ── AWB / Shipping ──

    def read_awb_pdf(self, order_id: int, **kwargs) -> bytes:
        """
        Download AWB PDF for an order.
        eMAG returns the PDF content directly from the awb/read_pdf endpoint.
        """
        payload: dict[str, Any] = {"order_id": order_id}
        data = _json_encode(payload)
        response = self.http.call(
            "POST",
            "awb/read_pdf",
            data=data,
            headers=dict(self._extra_headers),
            direct_response=True,
            **kwargs,
        )
        if hasattr(response, "content"):
            return response.content
        return b""

    # ── Invoice / Attachments ──

    def order_attachment_save(self, order_id: int, attachment_url: str, attachment_type: int = 1) -> EmagApiResponse:
        """
        Attach a document (invoice) to an order.

        attachment_type: 1 = invoice (default)
        """
        payload = [
            {
                "order_id": order_id,
                "url": attachment_url,
                "type": attachment_type,
                "force_download": 1,
            }
        ]
        data = _json_encode(payload)
        raw = self._call("POST", "order/attachments/save", data=data)
        return self._parse_response(raw)
