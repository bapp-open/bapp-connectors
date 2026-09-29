"""Order status catalogue — the statuses this particular shop actually has.

`ShopPort.update_order_status` speaks the framework's shared `OrderStatus`, which each adapter
translates through its own map. That is enough for the eight states every shop has in some form,
but a merchant can create their own statuses in Gomag, WooCommerce and most other platforms, and
those cannot be expressed as one of the eight.

This capability adds the missing half: read what the shop calls its statuses, and set one of
them by its raw value, without going through the translation. A caller that wants the shop's own
list needs both — listing alone would show statuses it could not then send.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.dto.base import BaseDTO

if TYPE_CHECKING:
    from bapp_connectors.core.dto import Order


class RemoteOrderStatus(BaseDTO):
    """One status as the shop itself defines it.

    `id` is what `set_order_status_raw` takes back; `label` is what the merchant sees in their
    own admin. They are often the same string (Gomag names its statuses in Romanian), which is
    why both are kept: a provider with numeric ids stays usable without a second lookup.
    """

    id: str
    label: str = ""
    #: The shared status this one maps to, when the adapter can tell. Informational.
    framework_status: str = ""
    #: Provider-specific leftovers (colour, order, visibility...).
    extra: dict = {}


class OrderStatusCatalogCapability(ABC):
    """Adapter can list the shop's own order statuses and set one by its raw value."""

    @abstractmethod
    def list_order_statuses(self) -> list[RemoteOrderStatus]:
        """Every status this shop defines, including the merchant's custom ones."""
        ...

    @abstractmethod
    def set_order_status_raw(self, order_id: str, raw_status: str) -> Order:
        """Set the status by the shop's own value, skipping the framework translation."""
        ...
