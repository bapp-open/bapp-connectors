"""
Vendigo shop adapter — implements ShopPort + InvoiceAttachmentCapability.

This is the main entry point for the Vendigo integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import InvoiceAttachmentCapability
from bapp_connectors.core.dto import (
    OrderStatus,
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
)
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.vendigo.client import VendigoApiClient
from bapp_connectors.providers.shop.vendigo.manifest import manifest
from bapp_connectors.providers.shop.vendigo.mappers import (
    order_from_vendigo,
    orders_from_vendigo,
    products_from_vendigo,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class VendigoShopAdapter(ShopPort, InvoiceAttachmentCapability):
    """
    Vendigo marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    - InvoiceAttachmentCapability: attach invoices to orders
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=BearerAuth(token=credentials.get("token", "")),
                provider_name="vendigo",
            )

        self.client = VendigoApiClient(http_client=http_client)

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
        raw_orders = self.client.get_orders(created_after=since)
        return orders_from_vendigo(raw_orders)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(order_id)
        return order_from_vendigo(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        raw_products = self.client.get_products()
        return products_from_vendigo(raw_products)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        # Vendigo API does not expose a direct stock update endpoint.
        # Stock is managed through the Vendigo dashboard or product feed.
        raise NotImplementedError("Vendigo does not support direct stock updates via API.")

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        # Vendigo API does not expose a direct price update endpoint.
        raise NotImplementedError("Vendigo does not support direct price updates via API.")

    def update_order_status(self, order_id: str, status: OrderStatus) -> "Order":
        raise NotImplementedError("Order status update is not supported by this provider.")

    # ── InvoiceAttachmentCapability ──

    def attach_invoice(self, order_id: str, invoice_url: str) -> bool:
        try:
            self.client.order_attachment(order_id=order_id, invoice_url=invoice_url)
            return True
        except Exception:
            return False
