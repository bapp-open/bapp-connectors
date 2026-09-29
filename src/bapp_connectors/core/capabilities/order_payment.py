"""Marking a shop order as paid.

`ShopPort` can move an order's status, and nothing else. It cannot say "the money arrived",
which is a different fact: a shop tracks payment separately from fulfilment, and the two do not
always move together — a bank transfer is settled days after the order was accepted, a COD is
collected after it shipped.

Providers express it differently. WooCommerce has a flag on the order itself, which also stamps
the payment date. PrestaShop has no flag: an order is paid when it sits in a state whose `paid`
marker is set, so marking it paid means moving it to such a state. The capability hides that.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Order


class OrderPaymentCapability(ABC):
    """Adapter can tell the shop that an order has been paid."""

    @abstractmethod
    def mark_order_paid(
        self,
        order_id: str,
        *,
        amount: Decimal | None = None,
        method: str = "",
        transaction_id: str = "",
        paid_at: str = "",
    ) -> Order:
        """Record the payment on the shop side and return the order as it stands afterwards.

        Everything but `order_id` is best effort: a provider that cannot store the amount, the
        method or the transaction reference ignores them rather than refusing the call. A
        provider that cannot express payment at all does not implement this capability.
        """
        ...
