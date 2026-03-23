"""
eMAG shop adapter — implements ShopPort + BulkUpdateCapability + InvoiceAttachmentCapability.

This is the main entry point for the eMAG integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import BulkUpdateCapability, InvoiceAttachmentCapability
from bapp_connectors.core.dto import (
    BulkResult,
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
    ProductUpdate,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.emag.client import EmagApiClient
from bapp_connectors.providers.shop.emag.manifest import EMAG_BASE_URLS, manifest
from bapp_connectors.providers.shop.emag.mappers import (
    order_from_emag,
    orders_from_emag,
    products_from_emag,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class EmagShopAdapter(ShopPort, BulkUpdateCapability, InvoiceAttachmentCapability):
    """
    eMAG marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - BulkUpdateCapability: batch product updates
    - InvoiceAttachmentCapability: attach invoices to orders
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials
        self.country = credentials.get("country", "RO")

        # Resolve base URL for the configured country
        base_url = EMAG_BASE_URLS.get(self.country, EMAG_BASE_URLS["RO"])

        if http_client is None:
            from bapp_connectors.core.http import BasicAuth

            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=BasicAuth(credentials.get("username", ""), credentials.get("password", "")),
                provider_name="emag",
            )
        else:
            # Override the base_url on the provided http_client for the correct country
            http_client.base_url = base_url.rstrip("/") + "/"

        self.client = EmagApiClient(http_client=http_client)

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
        return orders_from_emag(response, country=self.country)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return order_from_emag(data, country=self.country)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        return products_from_emag(response)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_product(
            [
                {
                    "part_number": product_id,
                    "stock": [{"warehouse_id": 1, "value": quantity}],
                }
            ]
        )

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        self.client.update_product(
            [
                {
                    "part_number": product_id,
                    "sale_price": str(price),
                }
            ]
        )

    # ── BulkUpdateCapability ──

    def bulk_update_products(self, updates: list[ProductUpdate]) -> BulkResult:
        items = []
        for update in updates:
            item: dict = {"part_number": update.barcode or update.product_id}

            if update.price is not None:
                item["sale_price"] = str(update.price)
            if update.stock is not None:
                item["stock"] = [{"warehouse_id": 1, "value": update.stock}]
            if update.name is not None:
                item["name"] = update.name

            items.append(item)

        succeeded = 0
        errors = []

        # eMAG product_offer/save accepts a batch of items
        if items:
            try:
                self.client.update_product(items)
                succeeded = len(items)
            except Exception as e:
                errors.append({"type": "product_offer_save", "error": str(e), "count": len(items)})

        return BulkResult(
            total=len(updates),
            succeeded=succeeded,
            failed=len(updates) - succeeded,
            errors=errors,
        )

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str) -> bool:
        try:
            self.client.order_attachment_save(order_id=int(order_id), attachment_url=invoice_url)
            return True
        except Exception:
            return False
