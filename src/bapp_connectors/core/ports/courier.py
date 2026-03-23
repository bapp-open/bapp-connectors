"""
Courier port — the common contract for all courier/shipping adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import AWBLabel, PaginatedResult, Shipment, TrackingEvent


class CourierPort(BasePort):
    """
    Common contract for all courier adapters.

    Covers: AWB generation, tracking, shipment management.
    """

    @abstractmethod
    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        """Generate an AWB (air waybill / shipping label) for a shipment."""
        ...

    @abstractmethod
    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        """Get tracking events for a shipment."""
        ...

    @abstractmethod
    def cancel_shipment(self, tracking_number: str) -> bool:
        """Cancel/delete a shipment. Returns True if successful."""
        ...

    @abstractmethod
    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        """List shipments with optional date filter and pagination."""
        ...
