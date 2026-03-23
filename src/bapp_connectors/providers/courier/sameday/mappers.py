"""
Sameday <-> DTO mappers.

Converts between raw Sameday API payloads and normalized framework DTOs.
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

SAMEDAY_STATUS_MAP: dict[str, ShipmentStatus] = {
    "InTransit": ShipmentStatus.IN_TRANSIT,
    "InDelivery": ShipmentStatus.OUT_FOR_DELIVERY,
    "Delivered": ShipmentStatus.DELIVERED,
    "Picked up": ShipmentStatus.PICKED_UP,
    "PickedUp": ShipmentStatus.PICKED_UP,
    "Canceled": ShipmentStatus.CANCELLED,
    "Cancelled": ShipmentStatus.CANCELLED,
    "InReturn": ShipmentStatus.RETURNED,
    "Returned": ShipmentStatus.RETURNED,
    "ParcelDetails": ShipmentStatus.CREATED,
    "FailedAttempt": ShipmentStatus.FAILED_DELIVERY,
}


def _map_sameday_status(status: str) -> ShipmentStatus:
    """Map a Sameday status string to a normalized ShipmentStatus."""
    return SAMEDAY_STATUS_MAP.get(status, ShipmentStatus.IN_TRANSIT)


# ── AWB label mapper ──


def awb_label_from_sameday(data: dict) -> AWBLabel:
    """Map a Sameday AWB generation response to an AWBLabel DTO."""
    return AWBLabel(
        tracking_number=data.get("awbNumber", ""),
        cost=data.get("awbCost"),
        extra={
            "parcels": data.get("parcels", []),
        },
        provider_meta=ProviderMeta(
            provider="sameday",
            raw_id=data.get("awbNumber", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Tracking mapper ──


def tracking_events_from_sameday(data: dict) -> list[TrackingEvent]:
    """Map a Sameday parcel status-history response to a list of TrackingEvent DTOs."""
    events: list[TrackingEvent] = []
    history = data.get("awbHistory", [])

    for entry in history:
        timestamp = None
        if raw_ts := entry.get("createdAt"):
            with contextlib.suppress(ValueError, TypeError):
                timestamp = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))

        events.append(
            TrackingEvent(
                status=_map_sameday_status(entry.get("statusState", "")),
                description=entry.get("statusLabel", entry.get("status", "")),
                location=entry.get("transitLocation", entry.get("county", "")),
                timestamp=timestamp,
                extra={
                    k: v
                    for k, v in entry.items()
                    if k not in ("statusState", "statusLabel", "status", "transitLocation", "county", "createdAt")
                },
            )
        )

    return events


# ── Shipment mapper ──


def _build_shipment_from_awb_entry(data: dict) -> Shipment:
    """Map a single entry from the AWB list to a Shipment DTO."""
    recipient_data = data.get("recipient", {})
    recipient = None
    if recipient_data:
        recipient = Address(
            street=recipient_data.get("address", ""),
            city=recipient_data.get("city", ""),
            region=recipient_data.get("county", ""),
            postal_code=recipient_data.get("postalCode", ""),
            country="RO",
        )

    parcels = []
    for p in data.get("parcels", []):
        parcels.append(
            Parcel(
                weight=p.get("weight", 0.0),
                width=p.get("width", 0.0),
                height=p.get("height", 0.0),
                length=p.get("length", 0.0),
                reference=p.get("awbNumber", ""),
            )
        )

    status_str = data.get("status", data.get("statusState", ""))
    status = _map_sameday_status(status_str) if status_str else ShipmentStatus.CREATED

    return Shipment(
        tracking_number=data.get("awbNumber", ""),
        status=status,
        carrier="sameday",
        recipient=recipient,
        parcels=parcels,
        extra={
            k: v for k, v in data.items() if k not in ("awbNumber", "status", "statusState", "recipient", "parcels")
        },
        provider_meta=ProviderMeta(
            provider="sameday",
            raw_id=data.get("awbNumber", ""),
            raw_payload=data,
            fetched_at=datetime.now(UTC),
        ),
    )


def shipments_from_sameday(response: dict) -> PaginatedResult[Shipment]:
    """Map a paginated Sameday AWB list response to PaginatedResult[Shipment]."""
    data_list = response.get("data", response.get("content", []))
    shipments = [_build_shipment_from_awb_entry(entry) for entry in data_list]

    total = response.get("pages", response.get("totalPages", 1))
    current_page = response.get("currentPage", response.get("page", 1))

    return PaginatedResult(
        items=shipments,
        cursor=str(current_page + 1) if current_page < total else None,
        has_more=current_page < total,
        total=response.get("nrOfElements", response.get("totalElements")),
    )


# ── Shipment request builder ──


def build_awb_payload(shipment: Shipment, pickup_point_id: int, service_id: int = 7) -> dict:
    """
    Build a Sameday AWB creation payload from a normalized Shipment DTO.

    Args:
        shipment: The shipment to generate an AWB for.
        pickup_point_id: Sameday pickup point ID.
        service_id: Sameday service type ID (default 7 = standard).
    """
    recipient = shipment.recipient
    parcels = shipment.parcels or [Parcel(weight=1.0)]

    payload: dict = {
        "pickupPoint": pickup_point_id,
        "service": service_id,
        "packageType": 1,  # 1 = parcel
        "packageNumber": len(parcels),
        "packageWeight": sum(p.weight for p in parcels) or 1.0,
        "awbPayment": 1,  # 1 = sender pays
        "cashOnDelivery": 0,
        "insuredValue": 0,
        "thirdPartyPickup": 0,
    }

    if recipient:
        payload["awbRecipient"] = {
            "name": recipient.extra.get("name", ""),
            "phoneNumber": recipient.extra.get("phone", ""),
            "county": recipient.region,
            "city": recipient.city,
            "address": recipient.street,
            "postalCode": recipient.postal_code,
        }

    payload["parcels"] = [
        {
            "weight": p.weight or 1.0,
            "width": p.width,
            "height": p.height,
            "length": p.length,
            "isLast": i == len(parcels) - 1,
        }
        for i, p in enumerate(parcels)
    ]

    # Merge any extra fields (e.g. observation, cashOnDelivery overrides)
    if shipment.extra:
        for key in ("observation", "cashOnDelivery", "insuredValue", "awbPayment", "thirdPartyPickup", "service"):
            if key in shipment.extra:
                payload[key] = shipment.extra[key]

    return payload
