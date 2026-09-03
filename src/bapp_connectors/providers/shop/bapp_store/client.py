"""
Company Store API client: raw HTTP calls against the store's /api/ surface, no business logic.
"""

from __future__ import annotations

from typing import Any

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.auth import NoAuth
from bapp_connectors.providers.shop.bapp_store.errors import raise_for_status

CATEGORY_PATH = "content-type/store.storecategory/"
PRODUCT_PATH = "content-type/store.storeproduct/"
SYNC_TASK_PATH = "tasks/store.CatalogSyncTask"
ORDERS_EXPORT_PATH = "tasks/store.OrdersExportTask"
ORDER_EXPORT_PATH = "tasks/store.OrderExportTask"
PAGE_LIMIT = 100


class BappStoreClient:
    # One batch is one store transaction: long read timeout, never replayed by the retry wrapper.
    SYNC_TIMEOUT = (10, 300)

    def __init__(self, store_url: str, token: str, http_client=None):
        self.base_url = store_url.rstrip("/") + "/api/"
        # Explicit headers on every call: the registry-built client carries NoAuth for CUSTOM.
        self._headers = {"Authorization": f"Token {token}", "X-App-Slug": "sync"}
        self.http = http_client or ResilientHttpClient(base_url=self.base_url, auth=NoAuth(), provider_name="bapp_store")
        self.http.base_url = self.base_url

    def _call(self, method: str, path: str, **kwargs):
        try:
            return self.http.call(method, path, headers=self._headers, **kwargs)
        except requests.RequestException as exc:
            # A transport failure is no verdict from the store, so the caller must be free to retry it.
            raise ProviderError(f"Company Store request failed: {exc}", retryable=True) from exc

    def test_auth(self) -> bool:
        try:
            self._call("GET", CATEGORY_PATH, params={"page_size": 1})
        except AuthenticationError:
            return False
        return True

    def sync_task(self, payload: dict) -> dict:
        response = self._call("POST", SYNC_TASK_PATH, json=payload, direct_response=True, retry=False, timeout=self.SYNC_TIMEOUT)
        raise_for_status(response)
        return response.json()

    def list_categories(self) -> list[dict]:
        page = self._call("GET", CATEGORY_PATH, params={"page_size": PAGE_LIMIT})
        rows = list(page["results"])
        while page.get("next"):
            page = self._call("GET", page["next"])
            rows.extend(page["results"])
        return rows

    def find_products(self, code: str | None = None, page: int = 1) -> dict:
        params: dict[str, Any] = {"page_size": PAGE_LIMIT, "page": page}
        if code:
            params["code"] = code
        return self._call("GET", PRODUCT_PATH, params=params)

    def export_orders(self, since: str | None, cursor: str | None, limit: int = 50) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if cursor:
            params["cursor"] = cursor
        return self._call("GET", ORDERS_EXPORT_PATH, params=params)

    def export_order(self, number: str) -> dict:
        return self._call("GET", ORDER_EXPORT_PATH, params={"number": number})

    def set_webhook(self, url: str, secret_token: str) -> dict:
        return self.sync_task({"webhook": {"url": url, "secret": secret_token}})
