"""
Normalized DTOs for shipments and courier operations.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .base import BaseDTO
from .partner import Address


class ShipmentStatus(StrEnum):
    CREATED = "created"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED_DELIVERY = "failed_delivery"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class Parcel(BaseDTO):
    """A single parcel in a shipment."""

    weight: float = 0.0
    width: float = 0.0
    height: float = 0.0
    length: float = 0.0
    reference: str = ""
    extra: dict = {}


class TrackingEvent(BaseDTO):
    """A single tracking event in a shipment's history."""

    status: ShipmentStatus
    description: str = ""
    location: str = ""
    timestamp: datetime | None = None
    extra: dict = {}


class AWBLabel(BaseDTO):
    """Generated AWB label from a courier."""

    tracking_number: str
    label_pdf: bytes | None = None
    label_url: str = ""
    cost: float | None = None
    extra: dict = {}


class Shipment(BaseDTO):
    """Normalized shipment."""

    tracking_number: str = ""
    status: ShipmentStatus = ShipmentStatus.CREATED
    carrier: str = ""
    sender: Address | None = None
    recipient: Address | None = None
    parcels: list[Parcel] = []
    events: list[TrackingEvent] = []
    label_pdf: bytes | None = None
    estimated_delivery: datetime | None = None
    extra: dict = {}
