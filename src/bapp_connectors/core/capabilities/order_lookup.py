"""Order lookup capability — find a remote order by the number the customer sees."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Order


class OrderLookupCapability(ABC):
    """Adapter can resolve an order by its customer-facing number (not the internal id)."""

    @abstractmethod
    def find_order_by_reference(self, reference: str) -> Order | None:
        """Return the order whose customer-facing number is exactly `reference`, or None."""
        ...
