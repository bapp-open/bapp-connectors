"""
CEL.ro shop adapter — implements ShopPort.

This is the main entry point for the CEL.ro integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    OrderStatus,
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.cel.client import CelApiClient
from bapp_connectors.providers.shop.cel.manifest import manifest
from bapp_connectors.providers.shop.cel.mappers import (
    order_from_cel,
    orders_from_cel,
    products_from_cel,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class CelShopAdapter(ShopPort):
    """
    CEL.ro marketplace adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.country = credentials.get("country", "RO")

        if http_client is None:
            from bapp_connectors.core.http import NoAuth

            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=NoAuth(),  # CEL handles auth via login token, not HTTP basic
                provider_name="cel",
            )

        self.client = CelApiClient(
            http_client=http_client,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
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
        start = int(cursor) if cursor else 0
        kwargs = {}
        if since:
            kwargs["created_after"] = since
        results = self.client.get_orders(start=start, **kwargs)
        return orders_from_cel(results)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return order_from_cel(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        start = int(cursor) if cursor else 0
        results = self.client.get_products(start=start)
        return products_from_cel(results)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        # CEL does not have a documented stock update endpoint in the current API
        raise NotImplementedError("CEL.ro does not support direct stock updates via API")

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        # CEL does not have a documented price update endpoint in the current API
        raise NotImplementedError("CEL.ro does not support direct price updates via API")

    def update_order_status(self, order_id: str, status: OrderStatus) -> "Order":
        raise NotImplementedError("Order status update is not supported by this provider.")
