"""
Trendyol API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


def _json_encode(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


class TrendyolApiClient:
    """
    Low-level Trendyol API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, seller_id: str, country: str = "RO"):
        self.http = http_client
        self.seller_id = seller_id
        self.country = country

        # Add Trendyol-specific headers
        self._extra_headers = {
            "User-Agent": f"{self.seller_id} - BappConnectors",
            "Content-Type": "application/json;charset=utf-8",
            "storeFrontCode": self.country,
        }

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        headers = dict(self._extra_headers)
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def get_webhooks(self) -> dict:
        return self._call("GET", f"webhook/sellers/{self.seller_id}/webhooks")

    def test_auth(self) -> bool:
        try:
            self.get_webhooks()
            return True
        except Exception:
            return False

    # ── Orders ──

    def get_orders(
        self,
        page: int = 0,
        size: int = 200,
        created_after: datetime | None = None,
        status: str | None = None,
        order_id: str | None = None,
        shipment_package_ids: list[int] | None = None,
        order_by_field: str = "PackageLastModifiedDate",
        order_by_direction: str = "DESC",
        **kwargs,
    ) -> dict:
        params: dict[str, Any] = {
            "orderByField": order_by_field,
            "orderByDirection": order_by_direction,
            "page": page,
            "size": size,
        }
        if status:
            params["status"] = status
        if order_id:
            params["orderNumber"] = order_id
        if shipment_package_ids:
            params["shipmentPackageIds"] = ",".join(str(i) for i in shipment_package_ids)
        if created_after:
            params["startDate"] = int(created_after.timestamp() * 1000)
            from datetime import datetime as dt

            params["endDate"] = int(dt.now(UTC).timestamp() * 1000)

        return self._call("GET", f"order/sellers/{self.seller_id}/orders", params=params, **kwargs)

    def get_order(self, order_id: str) -> dict:
        res = self.get_orders(order_id=order_id)
        content = (res.get("content") or []) if isinstance(res, dict) else []
        return content[0] if content else {}

    def get_claims(self, start_ms: int, end_ms: int, page: int = 0, size: int = 50, **kwargs) -> dict:
        params = {"startDate": start_ms, "endDate": end_ms, "page": page, "size": size}
        return self._call("GET", f"order/sellers/{self.seller_id}/claims", params=params, **kwargs)

    # ── Products ──

    # Product v2 lists at most 100 contents per page and at most page x size = 10,000;
    # past that the `nextPageToken` of the previous answer continues the listing.
    PRODUCTS_PAGE_SIZE = 100

    def get_products(
        self,
        page: int = 0,
        per_page: int = PRODUCTS_PAGE_SIZE,
        approved: bool | None = None,
        next_page_token: str | None = None,
        **kwargs,
    ) -> dict:
        """Approved products, from Product v2 (`products/approved`).

        Product v1 (`GET product/sellers/{id}/products`) is switched off by Trendyol
        on 2026-10-15. v2 groups the listing by content, with the barcodes under
        `variants`; the answer is returned as Trendyol sends it. `approved` is kept
        for callers of the v1 signature: this endpoint only lists approved products.
        """
        params: dict[str, Any] = {"size": min(per_page, self.PRODUCTS_PAGE_SIZE)}
        if next_page_token:
            params["nextPageToken"] = next_page_token
        else:
            params["page"] = page
        params.update(kwargs.pop("params", None) or {})
        return self._call("GET", f"product/sellers/{self.seller_id}/products/approved", params=params, **kwargs)

    def batch_update_content(self, items: list[dict], **kwargs) -> dict:
        """Update the content (title, description...) of approved products, Product v2.

        Each item carries `contentId` plus only the fields to change; at most 1,000 per call.
        """
        data = _json_encode({"items": items})
        return self._call(
            "POST", f"product/sellers/{self.seller_id}/products/content-bulk-update", data=data, **kwargs
        )

    def batch_update_price_inventory(self, products: list[dict], **kwargs) -> dict:
        data = _json_encode({"items": products})
        return self._call(
            "POST", f"inventory/sellers/{self.seller_id}/products/price-and-inventory", data=data, **kwargs
        )

    def get_batch_result(self, batch_id: str, **kwargs) -> dict:
        return self._call("GET", f"product/sellers/{self.seller_id}/products/batch-requests/{batch_id}", **kwargs)

    # ── Categories ──

    def get_categories(self, **kwargs) -> dict:
        return self._call("GET", "product/product-categories", **kwargs)

    # ── AWB / Shipping ──

    def read_awb(self, awb_id: int, **kwargs) -> bytes:
        import requests as req

        res = self._call("GET", f"sellers/{self.seller_id}/common-label/query", params={"id": awb_id}, **kwargs)
        if isinstance(res, dict) and res.get("data"):
            label_url = res["data"][0].get("label", "")
            if label_url:
                r = req.get(label_url, stream=True, timeout=(5, 30))
                r.raise_for_status()
                return r.content
        return b""

    # ── Invoice ──

    def order_attachment(self, order_id: int, invoice_url: str) -> dict | str:
        data = _json_encode({"shipmentPackageId": order_id, "invoiceLink": invoice_url})
        return self._call("POST", f"sellers/{self.seller_id}/seller-invoice-links", data=data)

    # ── Finance ──

    def get_settlements(
        self,
        transaction_type: str,
        start_date: int,
        end_date: int,
        page: int = 0,
        size: int = 500,
        **kwargs,
    ) -> dict:
        params: dict[str, Any] = {
            "transactionType": transaction_type,
            "startDate": start_date,
            "endDate": end_date,
            "page": page,
            "size": size,
        }
        return self._call(
            "GET", f"finance/che/sellers/{self.seller_id}/settlements", params=params, **kwargs
        )

    def get_other_financials(
        self,
        transaction_type: str,
        start_date: int,
        end_date: int,
        page: int = 0,
        size: int = 500,
        **kwargs,
    ) -> dict:
        params: dict[str, Any] = {
            "transactionType": transaction_type,
            "startDate": start_date,
            "endDate": end_date,
            "page": page,
            "size": size,
        }
        return self._call(
            "GET", f"finance/che/sellers/{self.seller_id}/otherfinancials", params=params, **kwargs
        )

    # ── Webhooks ──

    def create_webhook(self, webhook: dict, **kwargs) -> dict | str:
        data = _json_encode(webhook)
        return self._call("POST", f"webhook/sellers/{self.seller_id}/webhooks", data=data, **kwargs)

    def list_webhooks(self, **kwargs) -> list | dict:
        return self._call("GET", f"webhook/sellers/{self.seller_id}/webhooks", **kwargs)

    def update_webhook(self, webhook_id: str, webhook: dict, **kwargs) -> dict | str:
        data = _json_encode(webhook)
        return self._call("PUT", f"webhook/sellers/{self.seller_id}/webhooks/{webhook_id}", data=data, **kwargs)

    def delete_webhook(self, webhook_id: str, **kwargs) -> dict | str:
        return self._call("DELETE", f"webhook/sellers/{self.seller_id}/webhooks/{webhook_id}", **kwargs)

    def activate_webhook(self, webhook_id: str, **kwargs) -> dict | str:
        return self._call("PUT", f"webhook/sellers/{self.seller_id}/webhooks/{webhook_id}/activate", **kwargs)

    def deactivate_webhook(self, webhook_id: str, **kwargs) -> dict | str:
        return self._call("PUT", f"webhook/sellers/{self.seller_id}/webhooks/{webhook_id}/deactivate", **kwargs)
