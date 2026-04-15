"""
WooCommerce shop adapter — implements ShopPort + product management + webhooks.

This is the main entry point for the WooCommerce integration.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    OAuthCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import (
    AttributeDefinition,
    AttributeValue,
    BulkResult,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
    ProductUpdate,
    ProductVariant,
    RelatedProductLink,
    WebhookEvent,
)
from bapp_connectors.core.http import BasicAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.woocommerce.client import WooCommerceApiClient
from bapp_connectors.providers.shop.woocommerce.manifest import manifest
from bapp_connectors.providers.shop.woocommerce.mappers import (
    ORDER_STATUS_TO_WOO,
    WOO_ORDER_STATUS_MAP,
    attribute_definition_from_woocommerce,
    attribute_definition_to_woocommerce,
    categories_from_woocommerce,
    category_from_woocommerce,
    order_from_woocommerce,
    orders_from_woocommerce,
    product_from_woocommerce,
    product_to_woocommerce,
    product_update_to_woocommerce,
    products_from_woocommerce,
    related_products_from_woocommerce,
    variant_from_woocommerce,
    variant_to_woocommerce,
    webhook_event_from_woocommerce,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class WooCommerceShopAdapter(
    ShopPort,
    BulkUpdateCapability,
    CategoryManagementCapability,
    AttributeManagementCapability,
    OAuthCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
    WebhookCapability,
):
    """
    WooCommerce shop adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - BulkUpdateCapability: batch product updates via /products/batch
    - ProductCreationCapability: create/delete products
    - ProductFullUpdateCapability: full product updates (name, desc, photos, categories)
    - CategoryManagementCapability: read + create categories
    - OAuthCapability: redirect-based key generation via /wc-auth/v1/authorize
    - WebhookCapability: receive and verify webhooks
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.consumer_key = credentials.get("consumer_key", "")
        self.consumer_secret = credentials.get("consumer_secret", "")
        self.domain = credentials.get("domain", "").rstrip("/")
        self.verify_ssl = str(credentials.get("verify_ssl", "true")).lower() != "false"

        # VAT configuration
        self._prices_include_vat = config.get("prices_include_vat", True)
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.19")))

        use_query_auth = config.get("use_query_auth", False)

        # The manifest carries a placeholder base_url; the real store domain
        # comes from per-connection credentials. Rebuild the client so requests
        # target the tenant's actual WooCommerce host.
        if self.domain:
            base_url = f"{self.domain}/wp-json/wc/v3/"
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(self.consumer_key, self.consumer_secret),
                provider_name="woocommerce",
            )
        elif http_client is None:
            http_client = ResilientHttpClient(
                base_url=f"{self.domain}/wp-json/wc/v3/",
                auth=BasicAuth(self.consumer_key, self.consumer_secret),
                provider_name="woocommerce",
            )

        self.client = WooCommerceApiClient(
            http_client=http_client,
            consumer_key=self.consumer_key,
            consumer_secret=self.consumer_secret,
            use_query_auth=use_query_auth,
        )

        # Status mapping (tenant-configurable overrides)
        self._status_mapper = StatusMapper.from_config(
            default_inbound=WOO_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_WOO,
            config=config,
        )

    # ── Price conversion ──
    # Framework prices are always NET. Convert when the provider uses gross.

    def _price_to_provider(self, net_price: Decimal) -> Decimal:
        """Convert a net price to the provider's expected format."""
        if self._prices_include_vat:
            return to_gross(net_price, self._vat_rate)
        return net_price

    def _price_from_provider(self, provider_price: Decimal) -> Decimal:
        """Convert a provider price to net (framework convention)."""
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
    # WooCommerce uses a pseudo-OAuth flow via /wc-auth/v1/authorize.
    # The user approves on the WC admin, then WC POSTs consumer_key + consumer_secret
    # to the callback URL. The POST body is passed as the "code" parameter.

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        params = {
            "app_name": "BApp",
            "scope": "read_write",
            "user_id": state,
            "return_url": redirect_uri,
            "callback_url": redirect_uri,
        }
        return f"{self.domain}/wc-auth/v1/authorize?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        # WooCommerce POSTs {consumer_key, consumer_secret, key_permissions} to callback_url.
        # The callback handler serializes that POST body as JSON and passes it as "code".
        data = json.loads(code) if isinstance(code, str) else code
        consumer_key = data.get("consumer_key", "")
        consumer_secret = data.get("consumer_secret", "")
        return OAuthTokens(
            access_token=consumer_key,
            extra={
                "credentials": {
                    "domain": self.domain,
                    "consumer_key": consumer_key,
                    "consumer_secret": consumer_secret,
                },
                "key_permissions": data.get("key_permissions", ""),
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        raise NotImplementedError("WooCommerce API keys do not expire.")

    # ── ShopPort ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        kwargs = {}
        if since:
            kwargs["after"] = since.isoformat()
        response = self.client.get_orders(page=page, **kwargs)
        if not isinstance(response, list):
            response = []
        return orders_from_woocommerce(
            response, page=page,
            price_from_provider=self._price_from_provider,
            status_mapper=self._status_mapper,
        )

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_woocommerce(
            data,
            price_from_provider=self._price_from_provider,
            status_mapper=self._status_mapper,
        )

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        woo_status = self._status_mapper.to_provider(status)
        if not woo_status:
            raise ValueError(f"Cannot map OrderStatus.{status} to a WooCommerce status")
        data = self.client.update_order(order_id, {"status": woo_status})
        return order_from_woocommerce(
            data,
            price_from_provider=self._price_from_provider,
            status_mapper=self._status_mapper,
        )

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        if not isinstance(response, list):
            response = []
        return products_from_woocommerce(response, page=page, price_from_provider=self._price_from_provider)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_product(int(product_id), {"stock_quantity": quantity, "manage_stock": True})

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        provider_price = self._price_to_provider(price)
        self.client.update_product(
            int(product_id),
            {"regular_price": str(provider_price)},
        )

    # ── ProductCreationCapability ──

    def create_product(self, product: Product) -> Product:
        data = product_to_woocommerce(product, price_to_provider=self._price_to_provider)
        result = self.client.create_product(data)
        return product_from_woocommerce(result, price_from_provider=self._price_from_provider)

    def delete_product(self, product_id: str) -> None:
        self.client.delete_product(product_id)

    # ── ProductFullUpdateCapability ──

    def update_product(self, update: ProductUpdate) -> None:
        data = product_update_to_woocommerce(update, price_to_provider=self._price_to_provider)
        self.client.update_product(int(update.product_id), data)

    # ── CategoryManagementCapability ──

    def get_categories(self) -> list[ProductCategory]:
        all_categories: list[ProductCategory] = []
        page = 1
        while True:
            response = self.client.get_categories(page=page)
            if not response:
                break
            all_categories.extend(categories_from_woocommerce(response))
            if len(response) < 100:
                break
            page += 1
        return all_categories

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        data: dict = {"name": name}
        if parent_id:
            data["parent"] = int(parent_id)
        result = self.client.create_category(data)
        return category_from_woocommerce(result)

    # ── AttributeManagementCapability ──

    def get_attributes(self) -> list[AttributeDefinition]:
        raw_attrs = self.client.get_attributes()
        result = []
        for raw in raw_attrs:
            attr_id = raw.get("id")
            terms = self.client.get_attribute_terms(attr_id) if attr_id else []
            result.append(attribute_definition_from_woocommerce(raw, terms))
        return result

    def get_attribute(self, attribute_id: str) -> AttributeDefinition:
        raw = self.client.get_attribute(int(attribute_id))
        terms = self.client.get_attribute_terms(int(attribute_id))
        return attribute_definition_from_woocommerce(raw, terms)

    def create_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        data = attribute_definition_to_woocommerce(attribute)
        created = self.client.create_attribute(data)
        attr_id = created.get("id")
        # Create terms/values
        created_terms = []
        if attr_id and attribute.values:
            for val in attribute.values:
                term = self.client.create_attribute_term(attr_id, {"name": val.name, "slug": val.slug or ""})
                created_terms.append(term)
        return attribute_definition_from_woocommerce(created, created_terms)

    def update_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        data = attribute_definition_to_woocommerce(attribute)
        self.client.update_attribute(int(attribute.attribute_id), data)
        return self.get_attribute(attribute.attribute_id)

    def delete_attribute(self, attribute_id: str) -> None:
        self.client.delete_attribute(int(attribute_id))

    def add_attribute_value(self, attribute_id: str, value: AttributeValue) -> AttributeValue:
        result = self.client.create_attribute_term(int(attribute_id), {"name": value.name, "slug": value.slug or ""})
        return AttributeValue(value_id=str(result.get("id", "")), name=result.get("name", ""), slug=result.get("slug", ""))

    # ── VariantManagementCapability ──

    def get_variants(self, product_id: str) -> list[ProductVariant]:
        all_variants: list[ProductVariant] = []
        page = 1
        while True:
            raw = self.client.get_variations(int(product_id), page=page)
            if not raw:
                break
            all_variants.extend(variant_from_woocommerce(v, price_from_provider=self._price_from_provider) for v in raw)
            if len(raw) < 100:
                break
            page += 1
        return all_variants

    def create_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data = variant_to_woocommerce(variant, price_to_provider=self._price_to_provider)
        result = self.client.create_variation(int(product_id), data)
        return variant_from_woocommerce(result, price_from_provider=self._price_from_provider)

    def update_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data = variant_to_woocommerce(variant, price_to_provider=self._price_to_provider)
        result = self.client.update_variation(int(product_id), int(variant.variant_id), data)
        return variant_from_woocommerce(result, price_from_provider=self._price_from_provider)

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        self.client.delete_variation(int(product_id), int(variant_id))

    def get_variant(self, product_id: str, variant_id: str) -> ProductVariant:
        result = self.client.get_variation(int(product_id), int(variant_id))
        return variant_from_woocommerce(result, price_from_provider=self._price_from_provider)

    # ── RelatedProductCapability ──

    def get_related_products(self, product_id: str) -> list[RelatedProductLink]:
        data = self.client.get_product(product_id)
        return related_products_from_woocommerce(data)

    def set_related_products(self, product_id: str, links: list[RelatedProductLink]) -> None:
        """Set upsell and cross-sell IDs. Note: related_ids are read-only in WooCommerce."""
        upsell_ids = [int(l.product_id) for l in links if l.link_type == "upsell"]
        cross_sell_ids = [int(l.product_id) for l in links if l.link_type == "crosssell"]
        update_data: dict = {}
        if upsell_ids or any(l.link_type == "upsell" for l in links):
            update_data["upsell_ids"] = upsell_ids
        if cross_sell_ids or any(l.link_type == "crosssell" for l in links):
            update_data["cross_sell_ids"] = cross_sell_ids
        if update_data:
            self.client.update_product(int(product_id), update_data)

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        """Batch update products via WooCommerce /products/batch endpoint.

        Sends all updates in a single API call. WooCommerce supports up to
        100 items per batch request.
        """
        batch_items = []
        for update in updates:
            item: dict = {"id": int(update.product_id)}
            if update.stock is not None:
                item["stock_quantity"] = update.stock
                item["manage_stock"] = True
            if update.price is not None:
                item["regular_price"] = str(self._price_to_provider(update.price))
            if update.name is not None:
                item["name"] = update.name
            if update.active is not None:
                item["status"] = "publish" if update.active else "draft"
            if update.sku is not None:
                item["sku"] = update.sku
            if update.extra:
                item.update(update.extra)
            batch_items.append(item)

        errors = []
        succeeded = 0
        # WooCommerce batch limit is 100 per request
        for i in range(0, len(batch_items), 100):
            chunk = batch_items[i : i + 100]
            try:
                result = self.client.batch_update_products(chunk)
                updated = result.get("update", [])
                succeeded += len(updated)
            except Exception as e:
                errors.append({"chunk_offset": i, "error": str(e)})

        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
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
