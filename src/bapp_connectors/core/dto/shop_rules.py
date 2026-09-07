"""
Shop-wide pricing rules pushed to a store that prices orders itself.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .base import BaseDTO


class OrderValueTier(BaseDTO):
    """Order-total discount step: gross order total >= min_total earns discount_percent."""

    min_total: Decimal
    discount_percent: Decimal


class ShopRules(BaseDTO):
    """Amounts are gross values in the store currency."""

    order_value_tiers: list[OrderValueTier] = []
    min_order_total: Decimal | None = None
    max_rolling_order_percent: Decimal = Decimal("0")
    currency: str = ""
    extra: dict = {}


class CustomerProductPercent(BaseDTO):
    """One SKU's resolved quantity discount for one customer."""

    sku: str
    discount_percent: Decimal


class CustomerPricing(BaseDTO):
    """One customer's resolved volume level.

    Percentages only. The panel resolves history into these numbers and the store multiplies;
    no trading history and no identifying data beyond the fiscal key ever leaves the panel.
    """

    customer_key: str
    order_value_percent: Decimal = Decimal("0")
    product_percents: list[CustomerProductPercent] = []
    computed_at: datetime | None = None
    extra: dict = {}
