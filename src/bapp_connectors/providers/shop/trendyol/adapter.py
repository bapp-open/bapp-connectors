"""
Trendyol shop adapter — implements ShopPort + BulkUpdateCapability + InvoiceAttachmentCapability.

This is the main entry point for the Trendyol integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability
from bapp_connectors.core.dto import (
    OrderStatus,
    BulkResult,
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
    ProductUpdate,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.trendyol.client import TrendyolApiClient
from bapp_connectors.providers.shop.trendyol.manifest import manifest
from bapp_connectors.providers.shop.trendyol.mappers import (
    order_from_trendyol,
    orders_from_trendyol,
    products_from_trendyol,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class TrendyolShopAdapter(ShopPort, BulkUpdateCapability, InvoiceAttachmentCapability):
    """
    Trendyol marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - BulkUpdateCapability: batch product updates
    - InvoiceAttachmentCapability: attach invoices to orders
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.seller_id = str(credentials.get("seller_id", ""))
        self.country = credentials.get("country", "RO")

        if http_client is None:
            from bapp_connectors.core.http import BasicAuth

            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BasicAuth(credentials.get("username", ""), credentials.get("password", "")),
                provider_name="trendyol",
            )

        self.client = TrendyolApiClient(
            http_client=http_client,
            seller_id=self.seller_id,
            country=self.country,
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
        page = int(cursor) if cursor else 0
        kwargs = {}
        if since:
            kwargs["created_after"] = since
        response = self.client.get_orders(page=page, **kwargs)
        return orders_from_trendyol(response)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_trendyol(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 0
        response = self.client.get_products(page=page, approved=True)
        return products_from_trendyol(response)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.batch_update_price_inventory([{"barcode": product_id, "quantity": quantity}])

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        self.client.batch_update_price_inventory(
            [
                {"barcode": product_id, "salePrice": str(price), "listPrice": str(price)},
            ]
        )

    def update_order_status(self, order_id: str, status: OrderStatus) -> "Order":
        raise NotImplementedError("Order status update is not supported by this provider.")

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        price_inventory_items = []
        product_items = []

        for update in updates:
            item: dict = {"barcode": update.barcode or update.product_id}
            has_name = update.name is not None

            if update.price is not None:
                item["salePrice"] = str(update.price)
                item["listPrice"] = str(update.price)
            if update.stock is not None:
                item["quantity"] = update.stock

            if has_name:
                item["title"] = update.name
                product_items.append(item)
            else:
                price_inventory_items.append(item)

        succeeded = 0
        errors = []

        if price_inventory_items:
            try:
                self.client.batch_update_price_inventory(price_inventory_items)
                succeeded += len(price_inventory_items)
            except Exception as e:
                errors.append({"type": "price_inventory", "error": str(e), "count": len(price_inventory_items)})

        if product_items:
            try:
                self.client.batch_update_products(product_items)
                succeeded += len(product_items)
            except Exception as e:
                errors.append({"type": "product", "error": str(e), "count": len(product_items)})

        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str) -> bool:
        try:
            self.client.order_attachment(order_id=int(order_id), invoice_url=invoice_url)
            return True
        except Exception:
            return False
