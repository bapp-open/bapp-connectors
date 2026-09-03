"""
Volume pricing capability: the store applies quantity and order-value pricing itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ShopRules


class VolumePricingCapability(ABC):
    """Adapter pushes shop-wide pricing rules and per-product quantity tiers.

    Convention for Product DTOs sent to such an adapter:
    ``extra["price_tiers"]`` is a list of ``{"min_quantity": str, "price": str}`` with
    materialised gross unit prices, and ``extra["bapp"]`` carries
    ``{"gross_price", "vat_rate", "unit", "discountable"}`` as strings/bools.
    """

    @abstractmethod
    def push_shop_rules(self, rules: ShopRules) -> None:
        """Replace the store's order-value tiers and minimum order total."""
        ...
