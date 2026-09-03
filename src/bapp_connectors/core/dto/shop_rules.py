"""
Shop-wide pricing rules pushed to a store that prices orders itself.
"""

from __future__ import annotations

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
    currency: str = ""
    extra: dict = {}
