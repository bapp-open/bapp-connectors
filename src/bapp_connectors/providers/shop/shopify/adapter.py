"""
Shopify Admin REST API adapter.

Key Shopify differences:
- Products always have at least one variant
- Prices live on variants, not the product
- Stock is managed via inventory_levels endpoint
- Auth: X-Shopify-Access-Token header
- Collections = categories
- Max 3 product options (size, color, material)
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import (
    BulkUpdateCapability,
    CategoryManagementCapability,
    OAuthCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    VariantManagementCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import (
    BulkResult,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
    ProductUpdate,
    ProductVariant,
    WebhookEvent,
)
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.shopify.client import ShopifyApiClient
from bapp_connectors.providers.shop.shopify.manifest import manifest
from bapp_connectors.providers.shop.shopify.mappers import (
    ORDER_STATUS_TO_SHOPIFY,
    SHOPIFY_ORDER_STATUS_MAP,
    category_from_shopify,
    order_from_shopify,
    orders_from_shopify,
    product_from_shopify,
    product_to_shopify,
    product_update_to_shopify,
    products_from_shopify,
    variant_from_shopify,
    variant_to_shopify,
    verify_shopify_webhook,
    webhook_event_from_shopify,
)

if TYPE_CHECKING:
    from datetime import datetime


class ShopifyShopAdapter(
    ShopPort,
    BulkUpdateCapability,
    CategoryManagementCapability,
    OAuthCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    VariantManagementCapability,
    WebhookCapability,
):
    """
    Shopify Admin REST API adapter.

    Implements: ShopPort + BulkUpdate + CategoryManagement + OAuth +
                ProductCreation + ProductFullUpdate + VariantManagement + Webhook
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        self._store_domain = credentials.get("store_domain", "").rstrip("/")
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        store_domain = self._store_domain
        access_token = credentials.get("access_token", "")
        api_version = config.get("api_version", "2024-01")
        base_url = f"https://{store_domain}/admin/api/{api_version}/"

        self._prices_include_vat = config.get("prices_include_vat", False)
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.19")))
        self._webhook_secret = credentials.get("webhook_secret", "")

        self._status_mapper = StatusMapper.from_config(
            default_inbound=SHOPIFY_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_SHOPIFY,
            config=config,
        )

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=MultiHeaderAuth({"X-Shopify-Access-Token": access_token}),
                provider_name="shopify",
            )
        else:
            http_client.base_url = base_url
            http_client.auth = MultiHeaderAuth({"X-Shopify-Access-Token": access_token})

        self.client = ShopifyApiClient(http_client=http_client)

    def _price_to_provider(self, net_price: Decimal) -> Decimal:
        if self._prices_include_vat:
            return to_gross(net_price, self._vat_rate)
        return net_price

    def _price_from_provider(self, provider_price: Decimal) -> Decimal:
        if self._prices_include_vat:
            return to_net(provider_price, self._vat_rate)
        return provider_price

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

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "scope": ",".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"https://{self._store_domain}/admin/oauth/authorize?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            f"https://{self._store_domain}/admin/oauth/access_token",
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
            },
        )
        access_token = response.get("access_token", "") if isinstance(response, dict) else ""
        scope = response.get("scope", "") if isinstance(response, dict) else ""
        return OAuthTokens(
            access_token=access_token,
            extra={
                "credentials": {
                    "store_domain": self._store_domain,
                    "access_token": access_token,
                },
                "scope": scope,
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        raise NotImplementedError("Shopify offline access tokens do not expire.")

    # ── ShopPort: Orders ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        kwargs: dict = {}
        if since:
            kwargs["params"] = {"created_at_min": since.isoformat()}
        since_id = int(cursor) if cursor else None
        response = self.client.get_orders(limit=250, since_id=since_id, **kwargs)
        return orders_from_shopify(response, limit=250, price_from_provider=self._price_from_provider, status_mapper=self._status_mapper)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return order_from_shopify(data, price_from_provider=self._price_from_provider, status_mapper=self._status_mapper)

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        if status == OrderStatus.CANCELLED:
            data = self.client.cancel_order(int(order_id))
            return order_from_shopify(data, price_from_provider=self._price_from_provider, status_mapper=self._status_mapper)
        # Shopify REST API only supports cancellation directly.
        # Fulfillment-based statuses (SHIPPED, DELIVERED) require the Fulfillment API.
        raise ValueError(
            f"Shopify REST API does not support setting status to {status.value}. "
            f"Only CANCELLED is supported. Fulfillment status changes require the Fulfillment API."
        )

    # ── ShopPort: Products ──

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        since_id = int(cursor) if cursor else None
        response = self.client.get_products(limit=250, since_id=since_id)
        return products_from_shopify(response, limit=250, price_from_provider=self._price_from_provider)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        # Shopify stock is per-variant via inventory_levels
        product = self.client.get_product(int(product_id))
        variants = product.get("variants", [])
        if variants:
            inventory_item_id = variants[0].get("inventory_item_id")
            if inventory_item_id:
                levels = self.client.get_inventory_level(inventory_item_id)
                if levels:
                    location_id = levels[0].get("location_id")
                    self.client.set_inventory_level({
                        "location_id": location_id,
                        "inventory_item_id": inventory_item_id,
                        "available": quantity,
                    })

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        provider_price = self._price_to_provider(price)
        product = self.client.get_product(int(product_id))
        variants = product.get("variants", [])
        if variants:
            self.client.update_variant(variants[0]["id"], {"price": str(provider_price)})

    # ── ProductCreationCapability ──

    def create_product(self, product: Product) -> Product:
        data = product_to_shopify(product, price_to_provider=self._price_to_provider)
        result = self.client.create_product(data)
        return product_from_shopify(result, price_from_provider=self._price_from_provider)

    def delete_product(self, product_id: str) -> None:
        self.client.delete_product(int(product_id))

    # ── CategoryManagementCapability ──

    def get_categories(self) -> list[ProductCategory]:
        custom = self.client.get_custom_collections()
        smart = self.client.get_smart_collections()
        return [category_from_shopify(c) for c in custom] + [category_from_shopify(c) for c in smart]

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        # Shopify collections don't support parent/child hierarchy
        result = self.client.create_custom_collection({"title": name})
        return category_from_shopify(result)

    # ── ProductFullUpdateCapability ──

    def update_product(self, update: ProductUpdate) -> None:
        data = product_update_to_shopify(update, price_to_provider=self._price_to_provider)
        if data:
            self.client.update_product(int(update.product_id), data)
        if update.price is not None:
            self.update_product_price(update.product_id, update.price, update.currency or "")
        if update.stock is not None:
            self.update_product_stock(update.product_id, update.stock)

    # ── VariantManagementCapability ──

    def get_variants(self, product_id: str) -> list[ProductVariant]:
        raw = self.client.get_variants(int(product_id))
        return [variant_from_shopify(v, price_from_provider=self._price_from_provider) for v in raw]

    def create_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data = variant_to_shopify(variant, price_to_provider=self._price_to_provider)
        result = self.client.create_variant(int(product_id), data)
        return variant_from_shopify(result, price_from_provider=self._price_from_provider)

    def update_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data = variant_to_shopify(variant, price_to_provider=self._price_to_provider)
        result = self.client.update_variant(int(variant.variant_id), data)
        return variant_from_shopify(result, price_from_provider=self._price_from_provider)

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        self.client.delete_variant(int(product_id), int(variant_id))

    def get_variant(self, product_id: str, variant_id: str) -> ProductVariant:
        result = self.client.get_variant(int(variant_id))
        return variant_from_shopify(result, price_from_provider=self._price_from_provider)

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        errors = []
        succeeded = 0
        for update in updates:
            try:
                self.update_product(update)
                succeeded += 1
            except Exception as e:
                errors.append({"product_id": update.product_id, "error": str(e)})
        return BulkResult(total=len(updates), succeeded=succeeded, failed=len(updates) - succeeded, errors=errors)

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        webhook_secret = secret or self._webhook_secret
        signature = headers.get("X-Shopify-Hmac-Sha256", headers.get("x-shopify-hmac-sha256", ""))
        if not signature or not webhook_secret:
            return False
        return verify_shopify_webhook(body, webhook_secret, signature)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        payload = json.loads(body)
        return webhook_event_from_shopify(headers, payload)

    def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        topics = events or self.manifest.webhooks.events
        results = []
        for topic in topics:
            result = self.client.create_webhook({"topic": topic, "address": url, "format": "json"})
            results.append(result)
        return {"webhooks": results}

    def list_webhooks(self) -> list[dict]:
        return self.client.get_webhooks()
