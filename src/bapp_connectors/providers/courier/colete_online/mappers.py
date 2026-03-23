"""
Colete Online <-> DTO mappers.

Converts between raw Colete Online API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    Address,
    AWBLabel,
    PaginatedResult,
    Parcel,
    ProviderMeta,
    Shipment,
    ShipmentStatus,
    TrackingEvent,
)

# ── Status mappings ──
# Colete Online uses various status strings depending on the underlying courier.
# We map the common ones to normalized ShipmentStatus.

CO_STATUS_MAP: dict[str, ShipmentStatus] = {
    "new": ShipmentStatus.CREATED,
    "pending": ShipmentStatus.CREATED,
    "processing": ShipmentStatus.CREATED,
    "confirmed": ShipmentStatus.CREATED,
    "picked_up": ShipmentStatus.PICKED_UP,
    "pickedup": ShipmentStatus.PICKED_UP,
    "in_transit": ShipmentStatus.IN_TRANSIT,
    "intransit": ShipmentStatus.IN_TRANSIT,
    "in_delivery": ShipmentStatus.OUT_FOR_DELIVERY,
    "out_for_delivery": ShipmentStatus.OUT_FOR_DELIVERY,
    "delivered": ShipmentStatus.DELIVERED,
    "cancelled": ShipmentStatus.CANCELLED,
    "canceled": ShipmentStatus.CANCELLED,
    "returned": ShipmentStatus.RETURNED,
    "failed": ShipmentStatus.FAILED_DELIVERY,
    "failed_delivery": ShipmentStatus.FAILED_DELIVERY,
}


def _map_co_status(status: str) -> ShipmentStatus:
    """Map a Colete Online status string to a normalized ShipmentStatus."""
    if not status:
        return ShipmentStatus.CREATED
    normalized = status.lower().strip().replace(" ", "_")
    return CO_STATUS_MAP.get(normalized, ShipmentStatus.IN_TRANSIT)


def _parse_datetime(value: str) -> datetime | None:
    """Parse a datetime string from Colete Online API."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
    # Try ISO format as fallback
    with contextlib.suppress(ValueError, TypeError):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


# ── AWB label mapper ──


def awb_label_from_co(data: dict) -> AWBLabel:
    """Map a Colete Online order creation response to an AWBLabel DTO."""
    tracking_number = data.get("trackingNumber", data.get("awbNumber", ""))
    unique_id = data.get("uniqueId", "")

    return AWBLabel(
        tracking_number=tracking_number,
        cost=data.get("price"),
        extra={
            "unique_id": unique_id,
            "courier_name": data.get("courierName", ""),
            "status": data.get("status", ""),
        },
        provider_meta=ProviderMeta(
            provider="colete_online",
            raw_id=unique_id or tracking_number,
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Tracking mapper ──


def tracking_events_from_co(data: dict) -> list[TrackingEvent]:
    """Map a Colete Online order status response to a list of TrackingEvent DTOs."""
    events: list[TrackingEvent] = []

    # The status response may contain a history list or a single status
    history = data.get("history", data.get("statusHistory", []))
    if isinstance(history, list):
        for entry in history:
            timestamp = _parse_datetime(entry.get("date", entry.get("createdAt", "")))
            events.append(
                TrackingEvent(
                    status=_map_co_status(entry.get("status", entry.get("statusCode", ""))),
                    description=entry.get("statusDescription", entry.get("description", entry.get("status", ""))),
                    location=entry.get("location", entry.get("county", "")),
                    timestamp=timestamp,
                    extra={
                        k: v
                        for k, v in entry.items()
                        if k not in ("status", "statusCode", "statusDescription", "description", "date", "createdAt", "location", "county")
                    },
                )
            )

    # If no history but we have a top-level status, create a single event
    if not events and data.get("status"):
        events.append(
            TrackingEvent(
                status=_map_co_status(data.get("status", "")),
                description=data.get("statusDescription", data.get("status", "")),
                timestamp=_parse_datetime(data.get("lastUpdate", data.get("date", ""))),
            )
        )

    return events


# ── Shipment mapper ──


def _build_shipment_from_order(data: dict) -> Shipment:
    """Map a single order entry to a Shipment DTO."""
    recipient_data = data.get("recipient", {})
    recipient = None
    if recipient_data:
        addr = recipient_data.get("address", {})
        contact = recipient_data.get("contact", {})
        recipient = Address(
            street=addr.get("street", ""),
            city=addr.get("city", ""),
            region=addr.get("county", ""),
            postal_code=addr.get("postalCode", ""),
            country=addr.get("countryCode", "RO"),
            extra={
                "name": contact.get("name", ""),
                "phone": contact.get("phone", ""),
                "email": contact.get("email", ""),
                "company": contact.get("company", ""),
                "number": addr.get("number", ""),
            },
        )

    sender_data = data.get("sender", {})
    sender = None
    if sender_data:
        addr = sender_data.get("address", {})
        contact = sender_data.get("contact", {})
        sender = Address(
            street=addr.get("street", ""),
            city=addr.get("city", ""),
            region=addr.get("county", ""),
            postal_code=addr.get("postalCode", ""),
            country=addr.get("countryCode", "RO"),
            extra={
                "name": contact.get("name", ""),
                "phone": contact.get("phone", ""),
                "email": contact.get("email", ""),
            },
        )

    packages_data = data.get("packages", {})
    parcels = []
    for p in packages_data.get("list", []):
        parcels.append(
            Parcel(
                weight=p.get("weight", 0.0),
                width=p.get("width", 0.0),
                height=p.get("height", 0.0),
                length=p.get("length", 0.0),
            )
        )

    tracking = data.get("trackingNumber", data.get("awbNumber", ""))
    status_str = data.get("status", "")

    return Shipment(
        tracking_number=tracking,
        status=_map_co_status(status_str),
        carrier=data.get("courierName", "colete_online"),
        sender=sender,
        recipient=recipient,
        parcels=parcels,
        extra={
            "unique_id": data.get("uniqueId", ""),
            "courier_name": data.get("courierName", ""),
            "price": data.get("price"),
        },
        provider_meta=ProviderMeta(
            provider="colete_online",
            raw_id=data.get("uniqueId", tracking),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def shipments_from_co(response: dict | list) -> PaginatedResult[Shipment]:
    """Map a Colete Online order list response to PaginatedResult[Shipment]."""
    if isinstance(response, list):
        data_list = response
    else:
        data_list = response.get("data", response.get("orders", []))

    shipments = [_build_shipment_from_order(entry) for entry in data_list]

    total = None
    cursor = None
    has_more = False
    if isinstance(response, dict):
        total = response.get("total", response.get("totalElements"))
        current_page = response.get("page", response.get("currentPage", 1))
        total_pages = response.get("pages", response.get("totalPages", 1))
        if current_page < total_pages:
            cursor = str(current_page + 1)
            has_more = True

    return PaginatedResult(
        items=shipments,
        cursor=cursor,
        has_more=has_more,
        total=total,
    )


# ── Order request builder ──


def build_order_payload(shipment: Shipment) -> dict:
    """
    Build a Colete Online order creation payload from a normalized Shipment DTO.
    """
    recipient = shipment.recipient
    sender = shipment.sender
    parcels = shipment.parcels or [Parcel(weight=1.0)]

    payload: dict = {}

    # Sender
    if sender:
        sender_contact = {
            "name": sender.extra.get("name", ""),
            "phone": sender.extra.get("phone", ""),
        }
        if sender.extra.get("email"):
            sender_contact["email"] = sender.extra["email"]
        if sender.extra.get("phone2"):
            sender_contact["phone2"] = sender.extra["phone2"]

        sender_address = {
            "countryCode": sender.country or "RO",
            "postalCode": sender.postal_code,
            "city": sender.city,
            "county": sender.region,
            "street": sender.street,
        }
        if sender.extra.get("number"):
            sender_address["number"] = sender.extra["number"]

        payload["sender"] = {"contact": sender_contact, "address": sender_address}

    # Recipient
    if recipient:
        recipient_contact = {
            "name": recipient.extra.get("name", ""),
            "phone": recipient.extra.get("phone", ""),
        }
        if recipient.extra.get("company"):
            recipient_contact["company"] = recipient.extra["company"]
        if recipient.extra.get("email"):
            recipient_contact["email"] = recipient.extra["email"]

        recipient_address = {
            "countryCode": recipient.country or "RO",
            "postalCode": recipient.postal_code,
            "city": recipient.city,
            "county": recipient.region,
            "street": recipient.street,
        }
        if recipient.extra.get("number"):
            recipient_address["number"] = recipient.extra["number"]

        payload["recipient"] = {"contact": recipient_contact, "address": recipient_address}

    # Packages
    payload["packages"] = {
        "type": shipment.extra.get("package_type", 2) if shipment.extra else 2,
        "content": shipment.extra.get("content", "") if shipment.extra else "",
        "list": [
            {
                "weight": p.weight or 1.0,
                "width": p.width,
                "height": p.height,
                "length": p.length,
            }
            for p in parcels
        ],
    }

    # Service
    service: dict = {}
    if shipment.extra:
        service["selectionType"] = shipment.extra.get("selection_type", "bestPrice")
        if "service_ids" in shipment.extra:
            service["serviceIds"] = shipment.extra["service_ids"]
        if "activation_id" in shipment.extra:
            service["activationId"] = shipment.extra["activation_id"]
        if "service_specific" in shipment.extra:
            service["specific"] = shipment.extra["service_specific"]
    if not service:
        service = {"selectionType": "bestPrice", "serviceIds": [1, 2, 3, 4]}
    payload["service"] = service

    # Extra options
    extra_options = []
    if shipment.extra and "extra_options" in shipment.extra:
        extra_options = shipment.extra["extra_options"]
    payload["extraOptions"] = extra_options

    return payload
