"""
Shop/marketplace port — the common contract for all shop adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from bapp_connectors.core.dto import Order, PaginatedResult, Product


class ShopPort(BasePort):
    """
    Common contract for all shop/marketplace adapters.

    Covers: orders, products, stock/price sync.
    """

    @abstractmethod
    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        """Fetch orders, optionally filtered by date or cursor for pagination."""
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order:
        """Fetch a single order by ID."""
        ...

    @abstractmethod
    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        """Fetch products with cursor-based pagination."""
        ...

    @abstractmethod
    def update_product_stock(self, product_id: str, quantity: int) -> None:
        """Update stock quantity for a product on the marketplace."""
        ...

    @abstractmethod
    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        """Update price for a product on the marketplace."""
        ...
