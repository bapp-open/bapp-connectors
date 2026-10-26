"""Order amounts capability -- the money of an order when the order feed itself carries no prices
(Temu: the retail price paid by the consumer, the seller's base price, the platform's deduction)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal

from bapp_connectors.core.dto.base import BaseDTO


class OrderLineAmounts(BaseDTO):
    item_id: str
    sku: str = ""
    quantity: Decimal
    unit_price_incl_vat: Decimal
    unit_price_excl_vat: Decimal
    vat_rate: Decimal
    line_total_incl_vat: Decimal
    base_price_total: Decimal
    discount_seller: Decimal
    discount_platform: Decimal
    estimated_settlement: Decimal
    extra: dict = {}


class OrderAmounts(BaseDTO):
    order_id: str
    currency: str
    lines: list[OrderLineAmounts]
    shipping_incl_vat: Decimal
    shipping_excl_vat: Decimal
    tax_total: Decimal
    customer_paid_total: Decimal
    estimated_revenue: Decimal
    estimated_revenue_deduction: Decimal
    refunds_total: Decimal
    source: Literal["amount_query", "invoice_detail"]
    extra: dict = {}


class OrderAmountCapability(ABC):
    """Adapter can fetch the amounts of one order separately from the order itself."""

    @abstractmethod
    def get_order_amounts(self, order_id: str) -> OrderAmounts:
        ...
