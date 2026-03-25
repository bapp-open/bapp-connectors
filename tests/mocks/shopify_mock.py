"""
Minimal Shopify API mock server for integration testing.

Simulates the Shopify Admin REST API with in-memory storage.
Run as a standalone process or import and use in tests.

Usage:
    python tests/mocks/shopify_mock.py  # starts on port 8899
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

# In-memory storage
_products: dict[int, dict] = {}
_variants: dict[int, dict] = {}
_orders: dict[int, dict] = {}
_webhooks: dict[int, dict] = {}
_collections: dict[int, dict] = {}
_smart_collections: dict[int, dict] = {}
_next_id = 1000


def _get_next_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def _reset():
    global _next_id
    _products.clear()
    _variants.clear()
    _orders.clear()
    _webhooks.clear()
    _collections.clear()
    _smart_collections.clear()
    _next_id = 1000
    # Seed with sample data
    _seed_data()


def _seed_data():
    """Add some initial test data."""
    pid = _get_next_id()
    vid = _get_next_id()
    _variants[vid] = {
        "id": vid, "product_id": pid, "title": "Default Title",
        "price": "19.99", "sku": "SEED-001", "barcode": "",
        "inventory_quantity": 10, "option1": "Default Title",
        "option2": None, "option3": None, "weight": 0.5, "weight_unit": "kg",
        "inventory_item_id": vid + 1000, "taxable": True,
    }
    _products[pid] = {
        "id": pid, "title": "Seed Product", "body_html": "A test product",
        "vendor": "Test Vendor", "product_type": "Test", "status": "active",
        "tags": "test, seed", "handle": "seed-product",
        "variants": [_variants[vid]],
        "images": [{"id": _get_next_id(), "src": "https://example.com/img.jpg", "alt": "Test", "position": 1}],
        "options": [{"name": "Title", "values": ["Default Title"]}],
        "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z",
    }

    cid = _get_next_id()
    _smart_collections[cid] = {
        "id": cid, "title": "Sale Items", "handle": "sale-items",
        "rules": [{"column": "tag", "relation": "equals", "condition": "sale"}],
    }

    oid = _get_next_id()
    _orders[oid] = {
        "id": oid, "name": "#1001", "order_number": 1001,
        "financial_status": "paid", "fulfillment_status": None,
        "total_price": "19.99", "currency": "RON",
        "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z",
        "line_items": [{"id": _get_next_id(), "product_id": pid, "sku": "SEED-001", "title": "Seed Product", "quantity": 1, "price": "19.99"}],
        "billing_address": {"first_name": "Test", "last_name": "User", "address1": "123 Test St", "city": "Bucharest", "country_code": "RO", "zip": "010101"},
        "shipping_address": {"first_name": "Test", "last_name": "User", "address1": "123 Test St", "city": "Bucharest", "country_code": "RO", "zip": "010101"},
        "email": "test@test.com",
    }


class ShopifyMockHandler(BaseHTTPRequestHandler):
    """Handles Shopify-like REST API requests."""

    def log_message(self, format, *args):
        pass  # suppress request logging

    def _send_json(self, data: Any, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _parse_query_params(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return {k: v[0] for k, v in params.items()}

    def _parse_path(self) -> tuple[str, str | None]:
        """Parse path into (resource, id).

        Examples:
            /admin/api/2024-01/products.json -> ('products', None)
            /admin/api/2024-01/products/123.json -> ('products', '123')
            /admin/api/2024-01/products/123/variants.json -> ('products/123/variants', None)
            /admin/api/2024-01/products/123/variants/456.json -> ('products/123/variants', '456')
        """
        path = self.path.split("?")[0]
        parts = path.strip("/").split("/")
        try:
            api_idx = parts.index("api")
            resource_parts = [p.replace(".json", "") for p in parts[api_idx + 2:]]
        except ValueError:
            resource_parts = [p.replace(".json", "") for p in parts]

        if not resource_parts:
            return ("", None)

        # 1 part: products
        if len(resource_parts) == 1:
            return (resource_parts[0], None)
        # 2 parts: products/123 or products/count
        if len(resource_parts) == 2:
            if resource_parts[1].isdigit():
                return (resource_parts[0], resource_parts[1])
            return (f"{resource_parts[0]}/{resource_parts[1]}", None)
        # 3 parts: products/123/variants
        if len(resource_parts) == 3:
            return (f"{resource_parts[0]}/{resource_parts[1]}/{resource_parts[2]}", None)
        # 4 parts: products/123/variants/456
        if len(resource_parts) == 4:
            return (f"{resource_parts[0]}/{resource_parts[1]}/{resource_parts[2]}", resource_parts[3])

        return ("/".join(resource_parts), None)

    def do_GET(self):
        resource, rid = self._parse_path()

        if resource == "shop":
            return self._send_json({"shop": {"id": 1, "name": "Test Shop", "domain": "test.myshopify.com"}})

        if resource == "products" and rid is None:
            params = self._parse_query_params()
            items = sorted(_products.values(), key=lambda p: p["id"])
            since_id = int(params.get("since_id", 0))
            if since_id:
                items = [p for p in items if p["id"] > since_id]
            limit = int(params.get("limit", 250))
            items = items[:limit]
            return self._send_json({"products": items})
        if resource == "products" and rid:
            p = _products.get(int(rid))
            return self._send_json({"product": p}, 200 if p else 404)
        if resource.startswith("products/") and resource.endswith("/variants"):
            pid = int(resource.split("/")[1])
            variants = [v for v in _variants.values() if v.get("product_id") == pid]
            return self._send_json({"variants": variants})
        if resource == "products/count":
            return self._send_json({"count": len(_products)})

        if resource.startswith("variants/") or (resource == "variants" and rid):
            vid = int(rid) if rid else int(resource.split("/")[1])
            v = _variants.get(vid)
            return self._send_json({"variant": v}, 200 if v else 404)

        if resource == "orders" and rid is None:
            params = self._parse_query_params()
            items = sorted(_orders.values(), key=lambda o: o["id"])
            since_id = int(params.get("since_id", 0))
            if since_id:
                items = [o for o in items if o["id"] > since_id]
            limit = int(params.get("limit", 250))
            items = items[:limit]
            return self._send_json({"orders": items})
        if resource == "orders" and rid:
            o = _orders.get(int(rid))
            return self._send_json({"order": o}, 200 if o else 404)

        if resource == "custom_collections":
            return self._send_json({"custom_collections": list(_collections.values())})

        if resource == "smart_collections":
            return self._send_json({"smart_collections": list(_smart_collections.values())})

        if resource == "webhooks":
            return self._send_json({"webhooks": list(_webhooks.values())})

        if resource == "inventory_levels":
            return self._send_json({"inventory_levels": [{"location_id": 1, "inventory_item_id": 1, "available": 10}]})

        self._send_json({"errors": "Not Found"}, 404)

    def do_POST(self):
        resource, rid = self._parse_path()
        body = self._read_body()

        if resource == "products":
            data = body.get("product", {})
            pid = _get_next_id()
            data["id"] = pid
            data.setdefault("status", "active")
            data.setdefault("created_at", "2024-01-01T00:00:00Z")
            data.setdefault("updated_at", "2024-01-01T00:00:00Z")
            # Create default variant if provided
            for i, v in enumerate(data.get("variants", [])):
                vid = _get_next_id()
                v["id"] = vid
                v["product_id"] = pid
                v.setdefault("inventory_item_id", vid + 1000)
                _variants[vid] = v
            if not data.get("variants"):
                vid = _get_next_id()
                default_variant = {"id": vid, "product_id": pid, "title": "Default Title", "price": "0.00", "sku": "", "inventory_quantity": 0, "option1": "Default Title", "inventory_item_id": vid + 1000}
                data["variants"] = [default_variant]
                _variants[vid] = default_variant
            data.setdefault("images", [])
            data.setdefault("options", [])
            _products[pid] = data
            return self._send_json({"product": data}, 201)

        if resource.startswith("products/") and resource.endswith("/variants"):
            pid = int(resource.split("/")[1])
            data = body.get("variant", {})
            vid = _get_next_id()
            data["id"] = vid
            data["product_id"] = pid
            data.setdefault("inventory_item_id", vid + 1000)
            _variants[vid] = data
            if pid in _products:
                _products[pid].setdefault("variants", []).append(data)
            return self._send_json({"variant": data}, 201)

        if resource == "webhooks":
            data = body.get("webhook", {})
            wid = _get_next_id()
            data["id"] = wid
            _webhooks[wid] = data
            return self._send_json({"webhook": data}, 201)

        if resource.startswith("orders/") and resource.endswith("/cancel"):
            oid = int(resource.split("/")[1])
            if oid in _orders:
                _orders[oid]["cancelled_at"] = "2024-01-15T00:00:00Z"
                _orders[oid]["financial_status"] = "voided"
                return self._send_json({"order": _orders[oid]})
            return self._send_json({"errors": "Not Found"}, 404)

        if resource.startswith("orders/") and resource.endswith("/close"):
            oid = int(resource.split("/")[1])
            if oid in _orders:
                _orders[oid]["closed_at"] = "2024-01-15T00:00:00Z"
                return self._send_json({"order": _orders[oid]})
            return self._send_json({"errors": "Not Found"}, 404)

        if resource.startswith("orders/") and resource.endswith("/open"):
            oid = int(resource.split("/")[1])
            if oid in _orders:
                _orders[oid].pop("closed_at", None)
                return self._send_json({"order": _orders[oid]})
            return self._send_json({"errors": "Not Found"}, 404)

        if resource == "custom_collections":
            data = body.get("custom_collection", {})
            cid = _get_next_id()
            data["id"] = cid
            _collections[cid] = data
            return self._send_json({"custom_collection": data}, 201)

        if resource == "inventory_levels/set":
            return self._send_json({"inventory_level": body}, 200)

        self._send_json({"errors": "Not Found"}, 404)

    def do_PUT(self):
        resource, rid = self._parse_path()
        body = self._read_body()

        if resource == "products" and rid:
            pid = int(rid)
            data = body.get("product", {})
            if pid in _products:
                _products[pid].update(data)
                return self._send_json({"product": _products[pid]})
            return self._send_json({"errors": "Not Found"}, 404)

        if resource.startswith("variants/") or (resource == "variants" and rid):
            vid = int(rid) if rid else int(resource.split("/")[1])
            data = body.get("variant", {})
            if vid in _variants:
                _variants[vid].update(data)
                return self._send_json({"variant": _variants[vid]})
            return self._send_json({"errors": "Not Found"}, 404)

        if resource == "orders" and rid:
            oid = int(rid)
            data = body.get("order", {})
            if oid in _orders:
                _orders[oid].update(data)
                return self._send_json({"order": _orders[oid]})

        self._send_json({"errors": "Not Found"}, 404)

    def do_DELETE(self):
        resource, rid = self._parse_path()

        if resource == "products" and rid:
            pid = int(rid)
            if pid in _products:
                # Delete associated variants
                for v in _products[pid].get("variants", []):
                    _variants.pop(v.get("id"), None)
                del _products[pid]
                return self._send_json({}, 200)

        if resource.startswith("products/") and "/variants" in resource and rid:
            parts = resource.split("/")
            pid = int(parts[1])
            vid = int(rid)
            _variants.pop(vid, None)
            if pid in _products:
                _products[pid]["variants"] = [v for v in _products[pid].get("variants", []) if v.get("id") != vid]
            return self._send_json({}, 200)

        if resource == "webhooks" and rid:
            _webhooks.pop(int(rid), None)
            return self._send_json({}, 200)

        self._send_json({"errors": "Not Found"}, 404)


def start_mock_server(port: int = 8899) -> HTTPServer:
    """Start the mock server in a background thread. Returns the server instance."""
    _reset()
    server = HTTPServer(("127.0.0.1", port), ShopifyMockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    print("Starting Shopify mock server on http://127.0.0.1:8899")
    _reset()
    server = HTTPServer(("127.0.0.1", 8899), ShopifyMockHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
