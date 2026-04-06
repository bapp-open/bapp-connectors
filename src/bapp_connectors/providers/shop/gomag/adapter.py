"""
Gomag shop adapter — implements ShopPort + optional product management capabilities.

This is the main entry point for the Gomag integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    AttributeManagementCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ShippingCapability,
)
from bapp_connectors.core.dto import (
    AttributeDefinition,
    AWBLabel,
    ConnectionTestResult,
    Contact,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
)
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.status_mapping import StatusMapper
from bapp_connectors.providers.shop.gomag.client import GomagApiClient
from bapp_connectors.providers.shop.gomag.manifest import manifest
from bapp_connectors.providers.shop.gomag.mappers import (
    DEFAULT_LANG,
    GOMAG_ORDER_STATUS_MAP,
    ORDER_STATUS_TO_GOMAG,
    _multilang,
    _normalize_gomag_list,
    attribute_from_gomag,
    attribute_to_gomag,
    attributes_from_gomag,
    awb_from_gomag,
    awbs_from_gomag,
    bulk_updates_to_gomag,
    carriers_from_gomag,
    categories_from_gomag,
    category_from_gomag,
    customers_from_gomag,
    inventory_item_to_gomag,
    order_from_gomag,
    order_to_gomag,
    orders_from_gomag,
    payment_methods_from_gomag,
    product_from_gomag,
    product_to_gomag,
    product_update_to_gomag,
    products_from_gomag,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from bapp_connectors.core.dto import AttributeValue, BulkResult, ProductUpdate


class GomagShopAdapter(
    ShopPort,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    BulkUpdateCapability,
    CategoryManagementCapability,
    AttributeManagementCapability,
    ShippingCapability,
):
    """
    Gomag shop adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - ProductCreationCapability: create / delete products
    - ProductFullUpdateCapability: partial product updates
    - BulkUpdateCapability: bulk inventory sync (stock + price by SKU)
    - CategoryManagementCapability: list / create categories
    - AttributeManagementCapability: list / create / update attributes

    Custom methods (no framework capability interface):
    - AWB / shipping: get_carriers, get_awbs, create_awb, generate_awb,
      delete_awb, print_awb, update_awb_status
    - Invoice: create_invoice, generate_invoice, cancel_invoice
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.token = credentials.get("token", "")
        self.shop_site = credentials.get("shop_site", "")
        self._lang = (config or {}).get("lang", DEFAULT_LANG)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=MultiHeaderAuth(
                    {
                        "ApiShop": self.shop_site,
                        "Apikey": self.token,
                        "User-Agent": "BappConnectors/1.0",
                        "Accept": "*/*",
                    }
                ),
                provider_name="gomag",
            )

        self.client = GomagApiClient(http_client=http_client)

        self._status_mapper = StatusMapper.from_config(
            default_inbound=GOMAG_ORDER_STATUS_MAP,
            default_outbound=ORDER_STATUS_TO_GOMAG,
            config=config,
        )

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
        response = self.client.get_orders(page=page)
        return orders_from_gomag(response, page=page, status_mapper=self._status_mapper)

    def get_order(self, order_id: str) -> Order:
        response = self.client.get_order(order_id)
        # Gomag returns {orders: {"id": {...}}} — extract the single order
        if isinstance(response, dict):
            orders = response.get("orders", {})
            if isinstance(orders, dict) and orders:
                data = next(iter(orders.values()))
            elif order_id in response:
                data = response[order_id]
            else:
                data = response
        else:
            data = response
        return order_from_gomag(data, status_mapper=self._status_mapper)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        return products_from_gomag(response, page=page)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        item = inventory_item_to_gomag(product_id, stock=quantity)
        self.client.update_product_inventory([item])

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        item = inventory_item_to_gomag(product_id, price=price)
        self.client.update_product_inventory([item])

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        gomag_status = self._status_mapper.to_provider(status)
        if not gomag_status:
            raise ValueError(f"Cannot map OrderStatus.{status} to a Gomag status")
        self.client.update_order_status(order_id, gomag_status)
        return self.get_order(order_id)

    def create_order(self, order: Order) -> Order:
        """Create an order on Gomag. Returns the created order."""
        payload = order_to_gomag(order)
        response = self.client.create_order(payload)
        items = _normalize_gomag_list(response)
        if items:
            return order_from_gomag(items[0], status_mapper=self._status_mapper)
        return order

    def add_order_note(self, order_id: str, note: str, is_public: bool = False) -> None:
        """Add a note to an order (internal or customer-visible)."""
        self.client.add_order_note(int(order_id), note, is_public=is_public)

    def add_order_file(self, order_id: str, url: str, name: str = "") -> None:
        """Attach a file URL to an order."""
        self.client.add_order_file(int(order_id), url, name=name)

    # ── ProductCreationCapability ──

    def create_product(self, product: Product) -> Product:
        payload = product_to_gomag(product, lang=self._lang)
        response = self.client.create_product([payload])
        items = _normalize_gomag_list(response)
        if items:
            return product_from_gomag(items[0])
        return product

    def delete_product(self, product_id: str) -> None:
        self.client.delete_product([{"product_id": product_id}])

    # ── ProductFullUpdateCapability ──

    def update_product(self, update: ProductUpdate) -> None:
        payload = product_update_to_gomag(update, lang=self._lang)
        self.client.update_product([payload])

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        items, result = bulk_updates_to_gomag(updates)
        if items:
            self.client.update_product_inventory(items)
        return result

    # ── CategoryManagementCapability ──

    def get_categories(self) -> list[ProductCategory]:
        all_categories: list[ProductCategory] = []
        page = 1
        while True:
            response = self.client.get_categories(page=page)
            batch = categories_from_gomag(response)
            if not batch:
                break
            all_categories.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_categories

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        payload: dict = {"name": _multilang(name, self._lang)}
        if parent_id:
            payload["parent_id"] = int(parent_id)
        response = self.client.create_category([payload])
        items = _normalize_gomag_list(response)
        if items:
            return category_from_gomag(items[0])
        return ProductCategory(category_id="", name=name, parent_id=parent_id)

    def update_category(self, category_id: str, name: str | None = None, parent_id: str | None = None) -> None:
        """Update a category. Only non-None fields are sent."""
        payload: dict = {"id": int(category_id)}
        if name is not None:
            payload["name"] = _multilang(name, self._lang)
        if parent_id is not None:
            payload["parent_id"] = int(parent_id)
        self.client.update_category([payload])

    def delete_category(self, category_id: str) -> None:
        """Delete an empty category (no products or sub-categories)."""
        self.client.delete_category([{"id": int(category_id)}])

    # ── AttributeManagementCapability ──

    def get_attributes(self) -> list[AttributeDefinition]:
        all_attrs: list[AttributeDefinition] = []
        page = 1
        while True:
            response = self.client.get_attributes(page=page)
            batch = attributes_from_gomag(response)
            if not batch:
                break
            all_attrs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_attrs

    def get_attribute(self, attribute_id: str) -> AttributeDefinition:
        response = self.client.get_attributes(attribute_id=int(attribute_id))
        items = _normalize_gomag_list(response)
        if not items:
            raise ValueError(f"Attribute {attribute_id} not found")
        return attribute_from_gomag(items[0])

    def create_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        payload = attribute_to_gomag(attribute, lang=self._lang)
        response = self.client.create_attribute([payload])
        items = _normalize_gomag_list(response)
        if items:
            return attribute_from_gomag(items[0])
        return attribute

    def update_attribute(self, attribute: AttributeDefinition) -> AttributeDefinition:
        payload = attribute_to_gomag(attribute, lang=self._lang)
        response = self.client.update_attribute([payload])
        items = _normalize_gomag_list(response)
        if items:
            return attribute_from_gomag(items[0])
        return attribute

    def add_attribute_value(self, attribute_id: str, value: AttributeValue) -> AttributeValue:
        attr = self.get_attribute(attribute_id)
        existing_values = [*list(attr.values), value]
        payload = {
            "id": attribute_id,
            "values": [{"name": _multilang(v.name, self._lang)} for v in existing_values],
        }
        self.client.update_attribute([payload])
        return value

    # ── AWB / Shipping ──

    def get_carriers(self) -> list[dict]:
        """Return the list of configured shipping carriers."""
        response = self.client.get_carriers()
        return carriers_from_gomag(response)

    def get_order_awbs(self, order_id: str) -> list[AWBLabel]:
        response = self.client.get_awbs(order_id=int(order_id))
        return awbs_from_gomag(response)

    def get_awb_pdf(self, awb_id: str) -> bytes:
        """Download AWB label PDF. awb_id is the Gomag internal AWB ID."""
        result = self.client.print_awb(int(awb_id))
        # Gomag returns a dict with PDF data or URL
        if isinstance(result, bytes):
            return result
        if isinstance(result, dict) and result.get("pdf"):
            import base64
            return base64.b64decode(result["pdf"])
        return b""

    def get_awbs(self, order_id: int | None = None) -> list[AWBLabel]:
        """List AWB records, optionally filtered by order."""
        response = self.client.get_awbs(order_id=order_id)
        return awbs_from_gomag(response)

    def create_awb(
        self,
        order_id: int,
        carrier_id: int,
        awb_number: str,
        packages: int = 1,
        weight: float = 1.0,
    ) -> AWBLabel:
        """Manually create an AWB record for an order."""
        payload = {
            "orderId": order_id,
            "carrierId": carrier_id,
            "awbNumber": awb_number,
            "packages": packages,
            "weight": weight,
        }
        response = self.client.create_awb(payload)
        items = _normalize_gomag_list(response)
        if items:
            return awb_from_gomag(items[0])
        return AWBLabel(tracking_number=awb_number)

    def generate_awb(
        self,
        order_id: int,
        carrier_id: int,
        packages: int = 1,
        weight: float = 1.0,
    ) -> AWBLabel:
        """Generate an AWB automatically through the carrier's integrated API."""
        payload = {
            "orderId": order_id,
            "carrierId": carrier_id,
            "packages": packages,
            "weight": weight,
        }
        response = self.client.generate_awb(payload)
        items = _normalize_gomag_list(response)
        if items:
            return awb_from_gomag(items[0])
        return AWBLabel(tracking_number="")

    def delete_awb(self, awb_id: int) -> None:
        """Delete an AWB record."""
        self.client.delete_awb(awb_id)

    def print_awb(self, awb_id: int) -> dict:
        """Generate a printable shipping label. Returns raw response with PDF URL or data."""
        return self.client.print_awb(awb_id)

    def update_awb_status(self, awb_id: int, status: str, update_order_status: bool = False) -> None:
        """Update delivery status of an AWB."""
        self.client.update_awb_status(awb_id, status, update_order_status=update_order_status)

    # ── Invoice ──

    def create_invoice(
        self,
        order_id: int,
        number: str,
        date: str,
        series: str,
        due_date: str | None = None,
    ) -> dict:
        """Create and register an invoice for an order.

        Args:
            order_id: Internal order ID.
            number: Invoice number (e.g. "0001234").
            date: Invoice date (YYYY-MM-DD).
            series: Invoice series (e.g. "FCT").
            due_date: Optional payment deadline (YYYY-MM-DD).
        """
        payload: dict = {
            "orderId": order_id,
            "number": number,
            "date": date,
            "series": series,
        }
        if due_date:
            payload["dueDate"] = due_date
        return self.client.create_invoice(payload)

    def generate_invoice(self, order_id: int, series: str | None = None) -> dict:
        """Auto-generate an invoice using the store's configured settings."""
        return self.client.generate_invoice(order_id, series=series)

    def cancel_invoice(self, invoice_id: int) -> None:
        """Cancel/void an existing invoice."""
        self.client.cancel_invoice(invoice_id)

    # ── Customers ──

    def get_customers(
        self,
        customer_id: int | None = None,
        email: str | None = None,
        phone: str | None = None,
        updated: str | None = None,
        cursor: str | None = None,
    ) -> PaginatedResult[Contact]:
        """List customers with optional filtering.

        Args:
            customer_id: Filter by specific customer ID.
            email: Filter by email address.
            phone: Filter by phone number.
            updated: Filter by last-modified date (YYYY-MM-DD).
            cursor: Page number as string for pagination.
        """
        page = int(cursor) if cursor else 1
        response = self.client.get_customers(
            customer_id=customer_id,
            email=email,
            phone=phone,
            updated=updated,
            page=page,
        )
        items = customers_from_gomag(response)
        has_more = len(items) >= 100
        return PaginatedResult(
            items=items,
            cursor=str(page + 1) if has_more else None,
            has_more=has_more,
        )

    # ── Payment Methods ──

    def get_payment_methods(self) -> list[dict]:
        """Return the store's configured payment methods."""
        response = self.client.get_payment_methods()
        return payment_methods_from_gomag(response)
