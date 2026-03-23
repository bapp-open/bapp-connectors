"""
Magento 2 / Adobe Commerce shop adapter.

Key Magento API differences:
- Products are SKU-based (not ID-based) — /products/{sku}
- Stock updates use a separate endpoint /products/{sku}/stockItems/{itemId}
- Categories are a tree (flattened by the adapter)
- Order status changes via POST /orders/{id}/comments
- searchCriteria query params for all list endpoints
- Bearer token auth (integration access token)
- Store view scoping via URL path (/rest/{store_code}/V1/)
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import quote

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
)
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
)
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.magento.client import MagentoApiClient
from bapp_connectors.providers.shop.magento.manifest import manifest
from bapp_connectors.providers.shop.magento.mappers import (
    MAGENTO_ORDER_STATUS_MAP,
    ORDER_STATUS_TO_MAGENTO,
    attribute_definition_from_magento,
    categories_from_magento_list,
    category_from_magento,
    order_from_magento,
    orders_from_magento,
    product_from_magento,
    product_to_magento,
    product_update_to_magento,
    products_from_magento,
    related_link_to_magento,
    related_links_from_magento,
    variant_from_magento,
)

if TYPE_CHECKING:
    from datetime import datetime


class MagentoShopAdapter(
    ShopPort,
    BulkUpdateCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    CategoryManagementCapability,
    AttributeManagementCapability,
    VariantManagementCapability,
    RelatedProductCapability,
):
    """
    Magento 2 / Adobe Commerce adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates, order status
    - ProductCreationCapability: create/delete products (SKU-based)
    - ProductFullUpdateCapability: full product updates
    - CategoryManagementCapability: read + create categories
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}

        domain = credentials.get("domain", "").rstrip("/")
        access_token = credentials.get("access_token", "")
        store_code = config.get("store_code", "default")
        base_url = f"{domain}/rest/{store_code}/V1/"

        self._prices_include_vat = config.get("prices_include_vat", False)
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.19")))

        self._status_mapper = StatusMapper.from_config(
            default_inbound=MAGENTO_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_MAGENTO,
            config=config,
        )

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BearerAuth(token=access_token),
                provider_name="magento",
            )
        else:
            http_client.base_url = base_url
            http_client.auth = BearerAuth(token=access_token)

        self.client = MagentoApiClient(http_client=http_client)

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

    # ── ShopPort: Orders ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        page = int(cursor) if cursor else 1
        filters = []
        if since:
            filters.append({"field": "created_at", "value": since.strftime("%Y-%m-%d %H:%M:%S"), "condition": "gteq"})
        response = self.client.get_orders(page=page, filters=filters)
        return orders_from_magento(response, page=page, price_from_provider=self._price_from_provider, status_mapper=self._status_mapper)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return order_from_magento(data, price_from_provider=self._price_from_provider, status_mapper=self._status_mapper)

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        magento_status = self._status_mapper.to_provider(status)
        if not magento_status:
            raise ValueError(f"Cannot map OrderStatus.{status} to a Magento status")
        self.client.add_order_comment(int(order_id), status=magento_status)
        return self.get_order(order_id)

    # ── ShopPort: Products ──

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        return products_from_magento(response, page=page, price_from_provider=self._price_from_provider)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        # Magento needs the SKU — product_id might be entity_id or SKU
        # Try to get the product to find its stock item ID
        try:
            product = self.client.get_product(product_id)
            sku = product.get("sku", product_id)
        except Exception:
            sku = product_id

        ext = product.get("extension_attributes", {}) if isinstance(product, dict) else {}
        stock_item = ext.get("stock_item", {})
        item_id = stock_item.get("item_id", 1)

        self.client.update_stock(sku, item_id, {"qty": quantity, "is_in_stock": quantity > 0})

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        provider_price = self._price_to_provider(price)
        try:
            product = self.client.get_product(product_id)
            sku = product.get("sku", product_id)
        except Exception:
            sku = product_id
        self.client.update_product(sku, {"price": float(provider_price)})

    # ── ProductCreationCapability ──

    def create_product(self, product: Product) -> Product:
        data = product_to_magento(product, price_to_provider=self._price_to_provider)
        result = self.client.create_product(data)
        return product_from_magento(result, price_from_provider=self._price_from_provider)

    def delete_product(self, product_id: str) -> None:
        # product_id could be entity_id or SKU — try SKU first
        try:
            self.client.delete_product(product_id)
        except Exception:
            # If SKU fails, fetch by ID and get the SKU
            product = self.client.get_product(product_id)
            self.client.delete_product(product.get("sku", product_id))

    # ── ProductFullUpdateCapability ──

    def update_product(self, update: ProductUpdate) -> None:
        data = product_update_to_magento(update, price_to_provider=self._price_to_provider)
        # Magento uses SKU for updates — try product_id as SKU
        sku = update.sku or update.product_id
        self.client.update_product(sku, data)

        if update.stock is not None:
            self.update_product_stock(sku, update.stock)

    # ── CategoryManagementCapability ──

    def get_categories(self) -> list[ProductCategory]:
        response = self.client.get_category_list(page_size=1000)
        return categories_from_magento_list(response)

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        data: dict = {
            "name": name,
            "is_active": True,
            "parent_id": int(parent_id) if parent_id else 2,  # 2 = Default Category
        }
        result = self.client.create_category(data)
        return category_from_magento(result)

    # ── AttributeManagementCapability ──

    def get_attributes(self) -> list[AttributeDefinition]:
        all_attrs: list[AttributeDefinition] = []
        page = 1
        while True:
            response = self.client.get_attributes(page=page, page_size=100)
            items = response.get("items", [])
            all_attrs.extend(attribute_definition_from_magento(a) for a in items)
            if len(items) < 100:
                break
            page += 1
        return all_attrs

    def get_attribute(self, attribute_id: str) -> AttributeDefinition:
        raw = self.client.get_attribute(attribute_id)
        return attribute_definition_from_magento(raw)

    def create_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        data: dict = {
            "attribute_code": attribute.slug or attribute.name.lower().replace(" ", "_"),
            "frontend_input": attribute.attribute_type or "select",
            "default_frontend_label": attribute.name,
            "is_required": False,
        }
        if attribute.values:
            data["options"] = [{"label": v.name, "value": ""} for v in attribute.values]
        result = self.client.create_attribute(data)
        return attribute_definition_from_magento(result)

    def add_attribute_value(self, attribute_id: str, value: AttributeValue) -> AttributeValue:
        result = self.client.add_attribute_option(attribute_id, {"label": value.name})
        return AttributeValue(value_id=str(result) if result else "", name=value.name)

    # ── VariantManagementCapability ──

    def _resolve_sku(self, product_id: str) -> str:
        """Resolve a product_id to its SKU (Magento uses SKU for configurable endpoints)."""
        try:
            product = self.client.get_product(product_id)
            return product.get("sku", product_id)
        except Exception:
            return product_id

    def get_variants(self, product_id: str) -> list[ProductVariant]:
        sku = self._resolve_sku(product_id)
        children = self.client.get_configurable_children(sku)
        return [variant_from_magento(c, price_from_provider=self._price_from_provider) for c in children]

    def create_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        """Create a simple product and link it to the configurable parent."""
        parent_sku = self._resolve_sku(product_id)
        child_data = product_to_magento(
            type("_", (), {"name": variant.name or f"{parent_sku}-{variant.sku}", "sku": variant.sku, "price": variant.price,
                           "stock": variant.stock, "active": variant.active, "description": "", "categories": [], "attributes": []})(),
            price_to_provider=self._price_to_provider,
        )
        child_data["type_id"] = "simple"
        result = self.client.create_product(child_data)
        child_sku = result.get("sku", variant.sku)
        self.client.link_configurable_child(parent_sku, child_sku)
        return variant_from_magento(result, price_from_provider=self._price_from_provider)

    def update_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        sku = variant.sku or variant.variant_id
        data = product_update_to_magento(
            type("_", (), {"name": variant.name, "sku": variant.sku, "price": variant.price,
                           "stock": None, "active": variant.active, "description": None, "extra": {}})(),
            price_to_provider=self._price_to_provider,
        )
        result = self.client.update_product(sku, data)
        if variant.stock is not None:
            self.update_product_stock(sku, variant.stock)
        return variant_from_magento(result, price_from_provider=self._price_from_provider)

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        parent_sku = self._resolve_sku(product_id)
        try:
            self.client.remove_configurable_child(parent_sku, variant_id)
        except Exception:
            pass
        try:
            self.client.delete_product(variant_id)
        except Exception:
            pass

    # ── RelatedProductCapability ──

    def get_related_products(self, product_id: str) -> list[RelatedProductLink]:
        sku = self._resolve_sku(product_id)
        links: list[RelatedProductLink] = []
        for link_type in ("related", "upsell", "crosssell"):
            try:
                raw = self.client.get_product_links(sku, link_type)
                links.extend(related_links_from_magento(raw, link_type))
            except Exception:
                pass
        return links

    def set_related_products(self, product_id: str, links: list[RelatedProductLink]) -> None:
        sku = self._resolve_sku(product_id)
        items = [related_link_to_magento(sku, link) for link in links]
        if items:
            self.client.set_product_links(sku, items)

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        """Update products individually (Magento REST doesn't have a synchronous batch for arbitrary updates)."""
        errors = []
        succeeded = 0
        for update in updates:
            try:
                sku = update.sku or update.product_id
                data = product_update_to_magento(update, price_to_provider=self._price_to_provider)
                if data:
                    self.client.update_product(sku, data)
                if update.stock is not None:
                    self.update_product_stock(sku, update.stock)
                succeeded += 1
            except Exception as e:
                errors.append({"product_id": update.product_id, "error": str(e)})
        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )
