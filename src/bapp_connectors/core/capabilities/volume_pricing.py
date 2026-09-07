"""
Volume pricing capability: the store applies quantity and order-value pricing itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import CustomerPricing, ShopRules


class VolumePricingCapability(ABC):
    """Adapter pushes shop-wide pricing rules and per-product quantity tiers.

    Convention for Product DTOs sent to such an adapter:
    ``extra["price_tiers"]`` is a list of ``{"min_quantity": str, "price": str}`` with
    materialised gross unit prices, and ``extra["bapp"]`` carries
    ``{"gross_price", "vat_rate", "unit", "discountable"}`` as strings/bools.

    ``extra["bapp"]["max_rolling_percent"]`` is the highest rolling-window quantity percent any
    customer could earn on this product, as a 2-decimal string; the store needs it to compute the
    public "from" price without knowing any customer's history.
    """

    @abstractmethod
    def push_shop_rules(self, rules: ShopRules) -> None:
        """Replace the store's order-value tiers and minimum order total."""
        ...

    @abstractmethod
    def push_customer_pricing(self, records: list[CustomerPricing], *, full: bool = True) -> None:
        """Replace the store's per-customer volume levels.

        `full=True` means `records` is the complete set of customers who earn anything, and the
        store must drop every customer absent from it. That is the only thing that reliably
        removes a customer whose rolling window moved past their last large invoice.
        """
        ...
