"""
Shipping capability — optional interface for shop providers that manage AWBs per order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import AWBLabel


class ShippingCapability(ABC):
    """Adapter supports reading AWBs/shipments for orders."""

    @abstractmethod
    def get_order_awbs(self, order_id: str) -> list[AWBLabel]:
        """Return AWB labels associated with an order."""
        ...

    @abstractmethod
    def get_awb_pdf(self, awb_id: str) -> bytes:
        """Download AWB label PDF by tracking number or AWB identifier."""
        ...
