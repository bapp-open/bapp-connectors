"""
WooCommerce shop adapter — implements ShopPort + WebhookCapability.

This is the main entry point for the WooCommerce integration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import WebhookCapability
from bapp_connectors.core.dto import (
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
    WebhookEvent,
)
from bapp_connectors.core.http import BasicAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.woocommerce.client import WooCommerceApiClient
from bapp_connectors.providers.shop.woocommerce.manifest import manifest
from bapp_connectors.providers.shop.woocommerce.mappers import (
    order_from_woocommerce,
    orders_from_woocommerce,
    products_from_woocommerce,
    webhook_event_from_woocommerce,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class WooCommerceShopAdapter(ShopPort, WebhookCapability):
    """
    WooCommerce shop adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - WebhookCapability: receive and verify webhooks
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials
        self.consumer_key = credentials.get("consumer_key", "")
        self.consumer_secret = credentials.get("consumer_secret", "")
        self.domain = credentials.get("domain", "").rstrip("/")
        self.verify_ssl = str(credentials.get("verify_ssl", "true")).lower() != "false"

        if http_client is None:
            base_url = f"{self.domain}/wp-json/wc/v3/"
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(self.consumer_key, self.consumer_secret),
                provider_name="woocommerce",
            )

        self.client = WooCommerceApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        kwargs = {}
        if since:
            kwargs["after"] = since.isoformat()
        response = self.client.get_orders(page=page, **kwargs)
        if not isinstance(response, list):
            response = []
        return orders_from_woocommerce(response, page=page)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_woocommerce(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        if not isinstance(response, list):
            response = []
        return products_from_woocommerce(response, page=page)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_product(int(product_id), {"stock_quantity": quantity, "manage_stock": True})

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        self.client.update_product(
            int(product_id),
            {"regular_price": str(price)},
        )

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Verify WooCommerce webhook HMAC-SHA256 signature."""
        webhook_secret = secret or self.consumer_secret
        signature = headers.get(
            "X-WC-Webhook-Signature",
            headers.get("x-wc-webhook-signature", ""),
        )
        if not signature:
            return False

        computed = base64.b64encode(
            hmac.new(
                webhook_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        return hmac.compare_digest(signature, computed)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a WooCommerce webhook payload into a normalized WebhookEvent."""
        payload = json.loads(body)
        return webhook_event_from_woocommerce(headers, payload)

    def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """Register webhook URLs with WooCommerce for the given topics."""
        topics = events or self.manifest.webhooks.events
        results = []
        for topic in topics:
            data = {
                "name": f"bapp_{topic.replace('.', '_')}",
                "topic": topic,
                "delivery_url": url,
                "secret": self.consumer_secret,
                "status": "active",
            }
            result = self.client.create_webhook(data)
            results.append(result)
        return {"webhooks": results}

    def list_webhooks(self) -> list[dict]:
        """List registered webhooks from WooCommerce."""
        return self.client.get_webhooks()
