"""Customer details capability -- the un-masked buyer of an order, fetched on demand because the
marketplace audits or rate-limits the call (Temu `bg.order.decryptshippinginfo.get`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Contact


class CustomerDetailsCapability(ABC):
    """Adapter can return the real name, phone and address of an order's recipient."""

    @abstractmethod
    def get_customer_details(self, order_id: str) -> Contact:
        """The decrypted recipient; `email` stays empty when the marketplace only gives a relay address."""
        ...
