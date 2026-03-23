"""
PrestaShop API client — raw HTTP calls only, no business logic.

Uses the PrestaShop Webservice REST API with Basic Auth (API key as username, empty password).
Reference: https://devdocs.prestashop-project.org/8/webservice/
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
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

    def __init__(self, http_client: ResilientHttpClient, token: str, use_query_auth: bool = False):
        self.http = http_client
        self.token = token
        self._use_query_auth = use_query_auth
        # PrestaShop uses the API key as username with empty password for basic auth
        self._auth = HTTPBasicAuth(self.token, "")

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        """Make an authenticated API call.

        For write operations (POST/PUT), converts json payload to XML
        because PrestaShop only accepts XML for writes.
        """
        headers = kwargs.pop("headers", {})
        headers.setdefault("Output-Format", "JSON")

        # Convert JSON payload to XML for write operations
        if method in ("POST", "PUT", "PATCH") and "json" in kwargs:
            json_data = kwargs.pop("json")
            xml_str = self._dict_to_xml(json_data)
            kwargs["data"] = xml_str
            headers["Content-Type"] = "application/xml"
        else:
            headers.setdefault("Io-Format", "JSON")

        if self._use_query_auth:
            params = kwargs.pop("params", {})
            params["ws_key"] = self.token
            params["output_format"] = "JSON"
            return self.http.call(method, path, headers=headers, params=params, **kwargs)
        return self.http.call(method, path, headers=headers, auth=self._auth, **kwargs)

    @staticmethod
    def _dict_to_xml(data: dict) -> str:
        """Convert a dict payload to PrestaShop XML format.

        Input:  {"product": {"name": {...}, "price": "10.00"}}
        Output: <prestashop><product><name>...</name><price>10.00</price></product></prestashop>
        """
        root = ET.Element("prestashop")

        def _build(parent: ET.Element, obj):
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if key == "attrs":
                        continue
                    # Special case: "language" key with list value → multilang field
                    # Don't create <language> wrapper, items create their own <language> elements
                    if key == "language" and isinstance(val, list):
                        for item in val:
                            elem = ET.SubElement(parent, "language")
                            if isinstance(item, dict):
                                if "attrs" in item:
                                    for ak, av in item["attrs"].items():
                                        elem.set(ak, str(av))
                                elem.text = str(item.get("value", ""))
                            else:
                                elem.text = str(item)
                        continue
                    child = ET.SubElement(parent, key)
                    _build(child, val)
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        _build(parent, item)
                    else:
                        parent.text = str(item)
            else:
                parent.text = str(obj) if obj is not None else ""

        _build(root, data)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    @staticmethod
    def _unwrap_list(data: dict, resource_key: str, item_key: str) -> list[dict]:
        """Unwrap PrestaShop's nested list format into a flat list of dicts.

        Handles both formats:
        - Header auth: {"orders": {"order": [...]}}
        - Query auth:  {"orders": [...]}
        """
        container = data.get(resource_key, {})
        if not container:
            return []
        if isinstance(container, list):
            return container
        items = container.get(item_key, [])
        if isinstance(items, dict):
            return [items]
        return items if isinstance(items, list) else []

    # ── Auth / Connection Test ──

    def test_auth(self) -> dict:
        """Test authentication by fetching products (validates auth + permissions)."""
        try:
            result = self._call("GET", "products", params={"limit": "1"})
            if isinstance(result, dict) and "products" in result:
                return {"api": {"products": True, "orders": True, "categories": True,
                               "addresses": True, "countries": True, "customers": True,
                               "stock_availables": True, "images": True, "taxes": True}}
            return {}
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

    def update_product(self, product_id: int, data: dict, **kwargs) -> dict | list | str:
        """Update a product via PUT."""
        return self._call("PUT", f"products/{product_id}", json={"product": data}, **kwargs)

    def create_product(self, data: dict, **kwargs) -> dict | list | str:
        """Create a new product via POST."""
        result = self._call("POST", "products", json={"product": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("product", result)
        return result

    def delete_product(self, product_id: int, **kwargs) -> dict | list | str:
        """Delete a product."""
        return self._call("DELETE", f"products/{product_id}", **kwargs)

    def create_category(self, data: dict, **kwargs) -> dict | list | str:
        """Create a new category via POST."""
        result = self._call("POST", "categories", json={"category": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("category", result)
        return result

    def update_order(self, order_id: int, data: dict, **kwargs) -> dict | list | str:
        """Update an order via PUT."""
        return self._call("PUT", f"orders/{order_id}", json={"order": data}, **kwargs)

    def create_order_history(self, data: dict, **kwargs) -> dict | list | str:
        """Create an order history entry (PrestaShop's way to change order status)."""
        result = self._call("POST", "order_histories", json={"order_history": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("order_history", result)
        return result

    # ── Product Features (attributes) ──

    def get_product_features(self, **kwargs) -> list[dict]:
        result = self._call("GET", "product_features", params={"display": "full"}, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "product_features", "product_feature")
        return []

    def get_product_feature(self, feature_id: int, **kwargs) -> dict:
        result = self._call("GET", f"product_features/{feature_id}", **kwargs)
        return result.get("product_feature", {}) if isinstance(result, dict) else {}

    def create_product_feature(self, data: dict, **kwargs) -> dict | list | str:
        result = self._call("POST", "product_features", json={"product_feature": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("product_feature", result)
        return result

    def get_product_feature_values(self, feature_id: int, **kwargs) -> list[dict]:
        params = {"display": "full", "filter[id_feature]": str(feature_id)}
        result = self._call("GET", "product_feature_values", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "product_feature_values", "product_feature_value")
        return []

    def create_product_feature_value(self, data: dict, **kwargs) -> dict | list | str:
        result = self._call("POST", "product_feature_values", json={"product_feature_value": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("product_feature_value", result)
        return result

    # ── Product Options (variant attributes like Size, Color) ──

    def get_product_options(self, **kwargs) -> list[dict]:
        result = self._call("GET", "product_options", params={"display": "full"}, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "product_options", "product_option")
        return []

    def get_product_option_values(self, option_id: int, **kwargs) -> list[dict]:
        params = {"display": "full", "filter[id_attribute_group]": str(option_id)}
        result = self._call("GET", "product_option_values", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "product_option_values", "product_option_value")
        return []

    def create_product_option(self, data: dict, **kwargs) -> dict | list | str:
        result = self._call("POST", "product_options", json={"product_option": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("product_option", result)
        return result

    def create_product_option_value(self, data: dict, **kwargs) -> dict | list | str:
        result = self._call("POST", "product_option_values", json={"product_option_value": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("product_option_value", result)
        return result

    # ── Combinations (variants) ──

    def get_combinations(self, product_id: int | None = None, **kwargs) -> list[dict]:
        params: dict = {"display": "full"}
        if product_id:
            params["filter[id_product]"] = str(product_id)
        result = self._call("GET", "combinations", params=params, **kwargs)
        if isinstance(result, dict):
            return self._unwrap_list(result, "combinations", "combination")
        return []

    def get_combination(self, combination_id: int, **kwargs) -> dict:
        result = self._call("GET", f"combinations/{combination_id}", **kwargs)
        return result.get("combination", {}) if isinstance(result, dict) else {}

    def create_combination(self, data: dict, **kwargs) -> dict | list | str:
        result = self._call("POST", "combinations", json={"combination": data}, **kwargs)
        if isinstance(result, dict):
            return result.get("combination", result)
        return result

    def update_combination(self, combination_id: int, data: dict, **kwargs) -> dict | list | str:
        return self._call("PUT", f"combinations/{combination_id}", json={"combination": data}, **kwargs)

    def delete_combination(self, combination_id: int, **kwargs) -> dict | list | str:
        return self._call("DELETE", f"combinations/{combination_id}", **kwargs)

    # ── Images ──

    def get_images(self, **kwargs) -> dict | list | str:
        """Fetch product images."""
        return self._call("GET", "images/products", **kwargs)
