"""
Gomag shop adapter — implements ShopPort.

This is the main entry point for the Gomag integration.
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
from bapp_connectors.core.http import MultiHeaderAuth, ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.gomag.client import GomagApiClient
from bapp_connectors.providers.shop.gomag.manifest import manifest
from bapp_connectors.providers.shop.gomag.mappers import (
    order_from_gomag,
    orders_from_gomag,
    products_from_gomag,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class GomagShopAdapter(ShopPort):
    """
    Gomag shop adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.token = credentials.get("token", "")
        self.shop_site = credentials.get("shop_site", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=MultiHeaderAuth(
                    {
                        "ApiShop": self.shop_site,
                        "Apikey": self.token,
                    }
                ),
                provider_name="gomag",
            )

        self.client = GomagApiClient(http_client=http_client)

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
        return orders_from_gomag(response, page=page)

    def get_order(self, order_id: str) -> Order:
        response = self.client.get_order(order_id)
        # Gomag returns a dict; extract the single order
        if isinstance(response, dict):
            # Could be keyed by order_id or a wrapper
            if order_id in response:
                data = response[order_id]
            elif "order" in response:
                data = response["order"]
            else:
                # Try to find the order in the response values
                for v in response.values():
                    if isinstance(v, dict) and str(v.get("order_id", "")) == order_id:
                        data = v
                        break
                else:
                    data = response
        else:
            data = response
        return order_from_gomag(data)

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        response = self.client.get_products(page=page)
        return products_from_gomag(response, page=page)

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        # Gomag does not have a dedicated stock update endpoint in v1;
        # this is a placeholder that uses the available API surface.
        raise NotImplementedError("Gomag API v1 does not support direct stock updates.")

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        # Gomag does not have a dedicated price update endpoint in v1;
        # this is a placeholder that uses the available API surface.
        raise NotImplementedError("Gomag API v1 does not support direct price updates.")

    def update_order_status(self, order_id: str, status: OrderStatus) -> "Order":
        raise NotImplementedError("Order status update is not supported by this provider.")
