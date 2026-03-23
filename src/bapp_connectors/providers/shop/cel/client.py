"""
CEL.ro API client — raw HTTP calls only, no business logic.

CEL uses a login endpoint to obtain a bearer token, which is then
passed in the AUTH header for subsequent requests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class CelApiClient:
    """
    Low-level CEL.ro API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, username: str, password: str):
        self.http = http_client
        self.username = username
        self.password = password
        self._token: str | None = None

    # ── Token management ──

    def _get_token(self) -> str:
        """Authenticate with CEL and obtain a bearer token."""
        if self._token is not None:
            return self._token

        try:
            res = self.http.call(
                "POST",
                "login/actionLogin",
                data={"username": self.username, "password": self.password},
                timeout=15,
            )
        except Exception:
            logger.exception("CEL login failed")
            self._token = ""
            return ""

        if isinstance(res, dict) and res.get("tokenStatus"):
            self._token = res.get("message", "")
        else:
            self._token = ""
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        """Make an authenticated API call."""
        headers = kwargs.pop("headers", {})
        headers["AUTH"] = f"Bearer {self._get_token()}"
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test authentication by attempting to obtain a token."""
        return bool(self._get_token())

    # ── Orders ──

    def get_orders(
        self,
        start: int = 0,
        limit: int = 100,
        status: int | None = None,
        created_after: datetime | None = None,
        **kwargs,
    ) -> list[dict]:
        """Fetch orders with optional filters."""
        filters: dict[str, Any] = {}
        if created_after:
            filters["date"] = {"minDate": created_after.strftime("%Y-%m-%d %H:%M:%S")}
        if status is not None:
            filters["order_status"] = status

        data: dict[str, Any] = {"filters": filters, "start": start, "limit": limit}
        result = self._call("POST", "orders/getOrders", json=data, **kwargs)
        if isinstance(result, dict):
            return result.get("results", [])
        return []

    def get_order(self, order_id: int, **kwargs) -> dict:
        """Fetch a single order by ID."""
        result = self._call("POST", "orders/getOrder", json={"order": order_id}, **kwargs)
        return result if isinstance(result, dict) else {}

    # ── Categories ──

    def get_categories(self, **kwargs) -> list | dict:
        """Fetch supplier categories."""
        return self._call("POST", "import/getSupplierCategories", **kwargs)

    # ── Products ──

    def get_products(self, start: int = 0, limit: int = 100, **kwargs) -> list[dict]:
        """Fetch products."""
        data: dict[str, Any] = {"start": start, "limit": limit}
        result = self._call("POST", "import/getProducts", json=data, **kwargs)
        if isinstance(result, dict):
            return result.get("results", [])
        return []
