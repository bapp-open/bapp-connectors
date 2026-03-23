"""
PrestaShop API client — raw HTTP calls only, no business logic.

Uses the PrestaShop Webservice REST API with Basic Auth (API key as username, empty password).
Reference: https://devdocs.prestashop-project.org/8/webservice/
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from requests.auth import HTTPBasicAuth

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class PrestaShopApiClient:
    """
    Low-level PrestaShop Webservice API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, token: str):
        self.http = http_client
        self.token = token
        # PrestaShop uses the API key as username with empty password for basic auth
        self._auth = HTTPBasicAuth(self.token, "")

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        """Make an authenticated API call."""
        headers = kwargs.pop("headers", {})
        headers.setdefault("Io-Format", "JSON")
        headers.setdefault("Output-Format", "JSON")
        return self.http.call(method, path, headers=headers, auth=self._auth, **kwargs)

    @staticmethod
    def _unwrap_list(data: dict, resource_key: str, item_key: str) -> list[dict]:
        """Unwrap PrestaShop's nested list format into a flat list of dicts."""
        container = data.get(resource_key, {})
        if not container:
            return []
        items = container.get(item_key, [])
        if isinstance(items, dict):
            return [items]
        return items if isinstance(items, list) else []

    # ── Auth / Connection Test ──

    def test_auth(self) -> dict:
        """Test authentication by fetching the API root."""
        try:
            return self._call("GET", "")
        except Exception:
            return {}

    # ── Orders ──

    def get_orders(self, options: dict[str, Any] | None = None, **kwargs) -> list[dict]:
        """Fetch orders with optional filter/display options."""
        params = options or {}
        result = self._call("GET", "orders", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "orders", "order")
        return []

    def get_order(self, order_id: int, **kwargs) -> dict:
        """Fetch a single order by ID."""
        result = self._call("GET", f"orders/{order_id}", **kwargs)
        return result.get("order", {}) if isinstance(result, dict) else {}

    # ── Customers ──

    def get_customer(self, resource_id: int, **kwargs) -> dict:
        """Fetch a customer by ID."""
        result = self._call("GET", f"customers/{resource_id}", **kwargs)
        return result.get("customer", {}) if isinstance(result, dict) else {}

    # ── Addresses ──

    def get_address(self, resource_id: int, **kwargs) -> dict:
        """Fetch an address by ID."""
        result = self._call("GET", f"addresses/{resource_id}", **kwargs)
        return result.get("address", {}) if isinstance(result, dict) else {}

    # ── Countries / States ──

    def get_country(self, resource_id: int, **kwargs) -> dict:
        """Fetch a country by ID."""
        result = self._call("GET", f"countries/{resource_id}", **kwargs)
        return result.get("country", {}) if isinstance(result, dict) else {}

    def get_state(self, resource_id: int, **kwargs) -> dict:
        """Fetch a state/region by ID."""
        result = self._call("GET", f"states/{resource_id}", **kwargs)
        return result.get("state", {}) if isinstance(result, dict) else {}

    # ── Products ──

    def get_products(self, options: dict[str, Any] | None = None, **kwargs) -> list[dict]:
        """Fetch products with optional filter/display options."""
        params = options or {}
        result = self._call("GET", "products", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "products", "product")
        return []

    def get_product(self, resource_id: int, **kwargs) -> dict:
        """Fetch a single product by ID."""
        result = self._call("GET", f"products/{resource_id}", **kwargs)
        return result.get("product", {}) if isinstance(result, dict) else {}

    # ── Categories ──

    def get_categories(self, options: dict[str, Any] | None = None, **kwargs) -> list[dict]:
        """Fetch categories with optional filter/display options."""
        params = options or {}
        result = self._call("GET", "categories", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "categories", "category")
        return []

    # ── Stock ──

    def get_stock_available(
        self,
        stock_ids: list | None = None,
        product_ids: list | None = None,
        display_fields: list[str] | None = None,
        **kwargs,
    ) -> dict | list | str:
        """Fetch stock availability information."""
        if not display_fields:
            display_fields = ["id", "id_product", "quantity"]
        display = f"[{','.join(display_fields)}]"
        filter_type = "id"
        if product_ids:
            filter_type = "id_product"
        ids = product_ids or stock_ids
        params: dict[str, Any] = {"display": display}
        if ids:
            params[f"filter[{filter_type}]"] = ids
        return self._call("GET", "stock_availables", params=params, **kwargs)

    def update_stock_available(self, data: dict, **kwargs) -> dict | list | str:
        """Update stock availability."""
        return self._call("PUT", "stock_availables", json=data, **kwargs)

    # ── Images ──

    def get_images(self, **kwargs) -> dict | list | str:
        """Fetch product images."""
        return self._call("GET", "images/products", **kwargs)
