"""
PrestaShop shop adapter — implements ShopPort + product management + categories.

This is the main entry point for the PrestaShop integration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    VariantManagementCapability,
    WebhookCapability,
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
    WebhookEvent,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.prestashop.client import PrestaShopApiClient
from bapp_connectors.providers.shop.prestashop.manifest import manifest
from bapp_connectors.providers.shop.prestashop.mappers import (
    ORDER_STATUS_TO_PS,
    PRESTASHOP_ORDER_STATUS_MAP,
    PRESTASHOP_PERMISSIONS_REQUIRED,
    _extract_multilang_name,
    _multilang,
    attribute_from_prestashop_feature,
    attribute_from_prestashop_option,
    categories_from_prestashop,
    category_from_prestashop,
    order_from_prestashop,
    orders_from_prestashop,
    product_from_prestashop,
    product_to_prestashop,
    product_update_to_prestashop,
    products_from_prestashop,
    variant_from_prestashop,
)

if TYPE_CHECKING:
    from datetime import datetime


class PrestaShopShopAdapter(
    ShopPort,
    BulkUpdateCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    CategoryManagementCapability,
    AttributeManagementCapability,
    VariantManagementCapability,
    WebhookCapability,
):
    """
    PrestaShop webservice adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates, order status
    - ProductCreationCapability: create/delete products
    - ProductFullUpdateCapability: full product updates
    - CategoryManagementCapability: read + create categories
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._api_url = self._build_api_url(credentials.get("domain", ""))

        # VAT configuration
        self._prices_include_vat = config.get("prices_include_vat", True)
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.19")))

        # Status mapping
        self._status_mapper = StatusMapper.from_config(
            default_inbound=PRESTASHOP_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_PS,
            config=config,
        )

        if http_client is None:
            from bapp_connectors.core.http import NoAuth

            http_client = ResilientHttpClient(
                base_url=self._api_url,
                auth=NoAuth(),
                provider_name="prestashop",
            )

        self.client = PrestaShopApiClient(
            http_client=http_client,
            token=credentials.get("token", ""),
            use_query_auth=config.get("use_query_auth", False),
        )

    @staticmethod
    def _build_api_url(domain: str) -> str:
        domain = domain.rstrip("/")
        if domain.endswith("/api"):
            return domain + "/"
        return domain + "/api/"

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
            result = self.client.test_auth()
            if not result:
                return ConnectionTestResult(success=False, message="Authentication failed")

            api_resources = result.get("api", {})
            if api_resources:
                missing_perms = [perm for perm in PRESTASHOP_PERMISSIONS_REQUIRED if perm not in api_resources]
                if missing_perms:
                    return ConnectionTestResult(
                        success=False,
                        message=f"Missing API permissions: {', '.join(missing_perms)}",
                        details={"missing_permissions": missing_perms},
                    )

            return ConnectionTestResult(success=True, message="Connection successful")
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort: Orders ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        options: dict = {"display": "full"}
        if since:
            start_time = since.strftime("%Y-%m-%d %H:%M:%S")
            options["filter[date_add]"] = f"[{start_time},]"
            options["date"] = "1"

        raw_orders = self.client.get_orders(options=options)
        mapped_orders = [self._enrich_order(raw) for raw in raw_orders]
        return orders_from_prestashop(mapped_orders)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return self._enrich_order(data)

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        ps_state = self._status_mapper.to_provider(status)
        if not ps_state:
            raise ValueError(f"Cannot map OrderStatus.{status} to a PrestaShop order state")

        self.client.create_order_history({
            "id_order": int(order_id),
            "id_order_state": int(ps_state),
        })
        return self.get_order(order_id)

    def _enrich_order(self, order_data: dict) -> Order:
        """Fetch related address/customer data and map to Order DTO."""
        delivery_address = {}
        invoice_address = {}
        customer = {}
        delivery_country_iso = ""
        delivery_state_name = ""
        invoice_country_iso = ""
        invoice_state_name = ""

        if addr_id := order_data.get("id_address_delivery"):
            delivery_address = self.client.get_address(int(addr_id))
            if country_id := delivery_address.get("id_country"):
                country = self.client.get_country(int(country_id))
                delivery_country_iso = country.get("iso_code", "")
            if (state_id := delivery_address.get("id_state")) and int(state_id):
                state = self.client.get_state(int(state_id))
                delivery_state_name = state.get("name", "")

        if addr_id := order_data.get("id_address_invoice"):
            invoice_address = self.client.get_address(int(addr_id))
            if country_id := invoice_address.get("id_country"):
                country = self.client.get_country(int(country_id))
                invoice_country_iso = country.get("iso_code", "")
            if (state_id := invoice_address.get("id_state")) and int(state_id):
                state = self.client.get_state(int(state_id))
                invoice_state_name = state.get("name", "")

        if customer_id := order_data.get("id_customer"):
            customer = self.client.get_customer(int(customer_id))

        return order_from_prestashop(
            data=order_data,
            delivery_address=delivery_address,
            invoice_address=invoice_address,
            customer=customer,
            delivery_country_iso=delivery_country_iso,
            delivery_state_name=delivery_state_name,
            invoice_country_iso=invoice_country_iso,
            invoice_state_name=invoice_state_name,
        )

    # ── ShopPort: Products ──

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        per_page = 100
        offset = (page - 1) * per_page

        options = {"display": "full", "limit": f"{offset},{per_page}"}
        results = self.client.get_products(options=options)
        paginated = products_from_prestashop(results)

        if len(results) >= per_page:
            paginated = PaginatedResult(
                items=paginated.items,
                cursor=str(page + 1),
                has_more=True,
                total=paginated.total,
            )
        return paginated

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_stock_available(
            data={"stock_available": {"id_product": product_id, "quantity": quantity}},
        )

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        provider_price = self._price_to_provider(price)
        product_data = self.client.get_product(int(product_id))
        if product_data:
            product_data["price"] = str(provider_price)
            self.client.update_product(int(product_id), product_data)

    # ── ProductCreationCapability ──

    def create_product(self, product: Product) -> Product:
        data = product_to_prestashop(product, price_to_provider=self._price_to_provider)
        result = self.client.create_product(data)
        if isinstance(result, dict):
            return product_from_prestashop(result)
        return product

    def delete_product(self, product_id: str) -> None:
        self.client.delete_product(int(product_id))

    # ── ProductFullUpdateCapability ──

    def update_product(self, update: ProductUpdate) -> None:
        current = self.client.get_product(int(update.product_id))
        if not current:
            raise ValueError(f"Product {update.product_id} not found")

        changes = product_update_to_prestashop(update, price_to_provider=self._price_to_provider)
        current.update(changes)
        self.client.update_product(int(update.product_id), current)

        if update.stock is not None:
            self.update_product_stock(update.product_id, update.stock)

    # ── CategoryManagementCapability ──

    def get_categories(self) -> list[ProductCategory]:
        results = self.client.get_categories(options={"display": "full"})
        return categories_from_prestashop(results)

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        slug = name.lower().replace(" ", "-").replace(".", "")
        data: dict = {
            "name": _multilang(name),
            "active": "1",
            "id_parent": int(parent_id) if parent_id else 2,
            "link_rewrite": _multilang(slug),
        }
        result = self.client.create_category(data)
        if isinstance(result, dict):
            return category_from_prestashop(result)
        return ProductCategory(category_id="", name=name, parent_id=parent_id)

    # ── AttributeManagementCapability ──

    def get_attributes(self) -> list[AttributeDefinition]:
        """Fetch both product features and product options as AttributeDefinitions."""
        result: list[AttributeDefinition] = []
        # Features (informational attributes)
        for feature in self.client.get_product_features():
            values = self.client.get_product_feature_values(int(feature.get("id", 0)))
            result.append(attribute_from_prestashop_feature(feature, values))
        # Product options (variant attributes like Size, Color)
        for option in self.client.get_product_options():
            values = self.client.get_product_option_values(int(option.get("id", 0)))
            result.append(attribute_from_prestashop_option(option, values))
        return result

    def get_attribute(self, attribute_id: str) -> AttributeDefinition:
        # Try as feature first, then option
        try:
            feature = self.client.get_product_feature(int(attribute_id))
            if feature:
                values = self.client.get_product_feature_values(int(attribute_id))
                return attribute_from_prestashop_feature(feature, values)
        except Exception:
            pass
        # Fallback: return empty
        return AttributeDefinition(attribute_id=attribute_id, name="")

    def create_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        kind = attribute.extra.get("kind", "feature") if attribute.extra else "feature"
        if kind == "option":
            data = {"name": _multilang(attribute.name), "public_name": _multilang(attribute.name), "group_type": "select"}
            created = self.client.create_product_option(data)
            option_id = int(created.get("id", 0)) if isinstance(created, dict) else 0
            created_values = []
            for val in attribute.values:
                v = self.client.create_product_option_value({"id_attribute_group": option_id, "name": _multilang(val.name)})
                created_values.append(v if isinstance(v, dict) else {})
            return attribute_from_prestashop_option(created if isinstance(created, dict) else {}, created_values)
        data = {"name": _multilang(attribute.name)}
        created = self.client.create_product_feature(data)
        feature_id = int(created.get("id", 0)) if isinstance(created, dict) else 0
        created_values = []
        for val in attribute.values:
            v = self.client.create_product_feature_value({"id_feature": feature_id, "value": _multilang(val.name)})
            created_values.append(v if isinstance(v, dict) else {})
        return attribute_from_prestashop_feature(created if isinstance(created, dict) else {}, created_values)

    def add_attribute_value(self, attribute_id: str, value: AttributeValue) -> AttributeValue:
        # Try as feature value first
        result = self.client.create_product_feature_value({"id_feature": int(attribute_id), "value": _multilang(value.name)})
        if isinstance(result, dict):
            return AttributeValue(value_id=str(result.get("id", "")), name=value.name)
        return value

    # ── VariantManagementCapability ──

    def _build_option_values_map(self) -> dict:
        """Build a lookup: {option_value_id: {"name": "Red", "group_name": "Color"}}"""
        result = {}
        for option in self.client.get_product_options():
            group_name = _extract_multilang_name(option.get("name", "")) or _extract_multilang_name(option.get("public_name", ""))
            option_id = int(option.get("id", 0))
            for val in self.client.get_product_option_values(option_id):
                val_id = str(val.get("id", ""))
                val_name = _extract_multilang_name(val.get("name", ""))
                result[val_id] = {"name": val_name, "group_name": group_name}
        return result

    def get_variants(self, product_id: str) -> list[ProductVariant]:
        raw = self.client.get_combinations(product_id=int(product_id))
        option_map = self._build_option_values_map()
        return [variant_from_prestashop(c, option_map) for c in raw]

    def create_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data: dict = {"id_product": int(product_id)}
        if variant.sku:
            data["reference"] = variant.sku
        if variant.barcode:
            data["ean13"] = variant.barcode
        if variant.price is not None:
            data["price"] = str(variant.price)
        result = self.client.create_combination(data)
        if isinstance(result, dict):
            return variant_from_prestashop(result)
        return variant

    def update_variant(self, product_id: str, variant: ProductVariant) -> ProductVariant:
        data: dict = {"id_product": int(product_id)}
        if variant.sku:
            data["reference"] = variant.sku
        if variant.price is not None:
            data["price"] = str(variant.price)
        self.client.update_combination(int(variant.variant_id), data)
        result = self.client.get_combination(int(variant.variant_id))
        return variant_from_prestashop(result) if isinstance(result, dict) else variant

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        self.client.delete_combination(int(variant_id))

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        """Update products one by one (PrestaShop doesn't have a batch endpoint for arbitrary updates)."""
        errors = []
        succeeded = 0
        for update in updates:
            try:
                # Price update
                if update.price is not None:
                    self.update_product_price(update.product_id, update.price, update.currency or "")
                # Stock update
                if update.stock is not None:
                    self.update_product_stock(update.product_id, update.stock)
                # Full update for other fields
                if update.name is not None or update.description is not None or update.active is not None:
                    self.update_product(update)
                succeeded += 1
            except Exception as e:
                errors.append({"product_id": update.product_id, "error": str(e)})
        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )

    # ── WebhookCapability ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """PrestaShop webhooks don't use signature verification — always return True if body is valid."""
        try:
            import json
            json.loads(body)
            return True
        except Exception:
            return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Parse a PrestaShop webhook payload."""
        import json

        from bapp_connectors.core.dto import WebhookEventType
        payload = json.loads(body)

        # PrestaShop sends: {"id_order": 123} or {"id_product": 456} etc.
        event_type = WebhookEventType.UNKNOWN
        event_id = ""
        if "id_order" in payload:
            event_type = WebhookEventType.ORDER_UPDATED
            event_id = str(payload["id_order"])
        elif "id_product" in payload:
            event_type = WebhookEventType.PRODUCT_UPDATED
            event_id = str(payload["id_product"])

        from datetime import UTC, datetime
        return WebhookEvent(
            event_id=event_id,
            event_type=event_type,
            provider="prestashop",
            payload=payload,
            received_at=datetime.now(UTC),
        )
