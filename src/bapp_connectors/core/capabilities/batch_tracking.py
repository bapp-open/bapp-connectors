"""
Batch tracking capability — optional interface for couriers that return the tracking
of many shipments in one request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import TrackingEvent


class BatchTrackingCapability(ABC):
    """Adapter can fetch the tracking of several shipments at once (cheaper than `get_tracking` per AWB)."""

    @abstractmethod
    def get_tracking_batch(self, tracking_numbers: list[str]) -> dict[str, list[TrackingEvent]]:
        """Return {tracking number: events, oldest first}, like `CourierPort.get_tracking` for each.

        The adapter splits the list into the provider's request size. A number the provider
        does not know is missing from the result (or maps to an empty list)."""
        ...
