"""
GLS <-> DTO mappers.

Converts between raw GLS API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

import contextlib
import datetime
from datetime import UTC

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
# GLS status codes mapped to normalized ShipmentStatus.
# Reference: GLS status code documentation (codes 01-99)

GLS_STATUS_MAP: dict[str, ShipmentStatus] = {
    "01": ShipmentStatus.PICKED_UP,       # Handed over to GLS
    "02": ShipmentStatus.IN_TRANSIT,       # Left parcel center
    "03": ShipmentStatus.IN_TRANSIT,       # Reached parcel center
    "04": ShipmentStatus.OUT_FOR_DELIVERY, # Expected delivery during the day
    "05": ShipmentStatus.DELIVERED,        # Delivered
    "06": ShipmentStatus.IN_TRANSIT,       # Stored in parcel center
    "07": ShipmentStatus.IN_TRANSIT,       # Stored in parcel center
    "11": ShipmentStatus.FAILED_DELIVERY,  # Consignee on holidays
    "12": ShipmentStatus.FAILED_DELIVERY,  # Consignee absent
    "14": ShipmentStatus.FAILED_DELIVERY,  # Reception closed
    "15": ShipmentStatus.FAILED_DELIVERY,  # Not delivered lack of time
    "16": ShipmentStatus.FAILED_DELIVERY,  # No cash available
    "17": ShipmentStatus.RETURNED,         # Refused acceptance
    "18": ShipmentStatus.FAILED_DELIVERY,  # Need address info
    "20": ShipmentStatus.FAILED_DELIVERY,  # Wrong/incomplete address
    "23": ShipmentStatus.RETURNED,         # Returned to sender
    "40": ShipmentStatus.RETURNED,         # Returned to sender
    "51": ShipmentStatus.CREATED,          # Data entered, not yet handed over
    "54": ShipmentStatus.DELIVERED,        # Delivered to parcel box
    "55": ShipmentStatus.DELIVERED,        # Delivered at ParcelShop
    "58": ShipmentStatus.DELIVERED,        # Delivered at neighbour's
    "83": ShipmentStatus.PICKED_UP,        # Pickup data entered
    "84": ShipmentStatus.PICKED_UP,        # Pickup label produced
    "85": ShipmentStatus.OUT_FOR_DELIVERY, # Driver received pickup order
    "86": ShipmentStatus.IN_TRANSIT,       # Parcel reached center (pickup)
    "92": ShipmentStatus.DELIVERED,        # Delivered (pickup)
    "97": ShipmentStatus.DELIVERED,        # Placed to parcellocker
}


def _map_gls_status(status_code: str) -> ShipmentStatus:
    """Map a GLS status code to a normalized ShipmentStatus."""
    return GLS_STATUS_MAP.get(status_code, ShipmentStatus.IN_TRANSIT)


def _parse_gls_date(value: str) -> datetime.datetime | None:
    """
    Parse GLS date format: /Date(1739142000000+0100)/

    The timestamp is in milliseconds, optionally followed by a timezone offset.
    """
    if not value:
        return None
    try:
        inner = value.split("(")[1].split(")")[0]
        if "+" in inner:
            ts_str, tz_str = inner.split("+")
        elif "-" in inner and inner.index("-") > 0:
            ts_str, tz_str = inner.split("-")
        else:
            ts_str = inner
            tz_str = "0000"
        ts = int(ts_str)
        tz_hours = int(tz_str[:2])
        tz_minutes = int(tz_str[2:])
        tz_offset = datetime.timedelta(hours=tz_hours, minutes=tz_minutes)
        return datetime.datetime.fromtimestamp(ts / 1000, tz=UTC) - tz_offset + datetime.timedelta(hours=tz_hours, minutes=tz_minutes)
    except (ValueError, TypeError, IndexError):
        return None


# ── AWB label mapper ──


def awb_label_from_gls(data: dict) -> AWBLabel:
    """Map a GLS PrintLabels response to an AWBLabel DTO."""
    info_list = data.get("PrintLabelsInfoList", [])
    errors = data.get("PrintLabelsErrorList", [])

    tracking_number = ""
    parcel_id = 0
    if info_list:
        first = info_list[0]
        tracking_number = str(first.get("ParcelNumber", ""))
        parcel_id = first.get("ParcelId", 0)

    label_pdf = None
    raw_labels = data.get("Labels")
    if raw_labels:
        with contextlib.suppress(Exception):
            label_pdf = bytes(raw_labels)

    return AWBLabel(
        tracking_number=tracking_number,
        label_pdf=label_pdf,
        cost=None,
        extra={
            "parcel_id": parcel_id,
            "parcels": info_list,
            "errors": errors,
        },
        provider_meta=ProviderMeta(
            provider="gls",
            raw_id=tracking_number,
            raw_payload=data,
            fetched_at=datetime.datetime.now(UTC),
        ),
    )


# ── Tracking mapper ──


def tracking_events_from_gls(data: dict) -> list[TrackingEvent]:
    """Map a GLS GetParcelStatuses response to a list of TrackingEvent DTOs."""
    events: list[TrackingEvent] = []
    status_list = data.get("ParcelStatusList", [])

    for entry in status_list:
        timestamp = _parse_gls_date(entry.get("StatusDate", ""))
        status_code = entry.get("StatusCode", "")

        events.append(
            TrackingEvent(
                status=_map_gls_status(status_code),
                description=entry.get("StatusDescription", ""),
                location=entry.get("DepotCity", ""),
                timestamp=timestamp,
                extra={
                    "status_code": status_code,
                    "status_info": entry.get("StatusInfo", ""),
                    "depot_number": entry.get("DepotNumber", ""),
                },
            )
        )

    return events


# ── Shipment mapper ──


def _build_shipment_from_parcel_entry(data: dict) -> Shipment:
    """Map a single entry from the GLS parcel list to a Shipment DTO."""
    parcel_data = data.get("Parcel", {})
    delivery = parcel_data.get("DeliveryAddress") or {}
    pickup = parcel_data.get("PickupAddress") or {}

    recipient = None
    if delivery:
        recipient = Address(
            street=delivery.get("Street", ""),
            city=delivery.get("City", ""),
            postal_code=delivery.get("ZipCode", ""),
            country=delivery.get("CountryIsoCode", ""),
            extra={
                "name": delivery.get("Name", ""),
                "phone": delivery.get("ContactPhone", ""),
                "email": delivery.get("ContactEmail", ""),
            },
        )

    sender = None
    if pickup:
        sender = Address(
            street=pickup.get("Street", ""),
            city=pickup.get("City", ""),
            postal_code=pickup.get("ZipCode", ""),
            country=pickup.get("CountryIsoCode", ""),
            extra={
                "name": pickup.get("Name", ""),
                "phone": pickup.get("ContactPhone", ""),
            },
        )

    tracking_number = str(data.get("ParcelNumber", parcel_data.get("ParcelNumber", "")))
    parcels = [
        Parcel(
            weight=parcel_data.get("Weight", 0.0) or 0.0,
            reference=tracking_number,
        )
    ]

    return Shipment(
        tracking_number=tracking_number,
        status=ShipmentStatus.CREATED,
        carrier="gls",
        sender=sender,
        recipient=recipient,
        parcels=parcels,
        extra={
            "parcel_id": data.get("ParcelId", 0),
            "client_reference": data.get("ClientReference", parcel_data.get("ClientReference", "")),
            "cod_amount": parcel_data.get("CODAmount"),
        },
        provider_meta=ProviderMeta(
            provider="gls",
            raw_id=tracking_number,
            raw_payload=data,
            fetched_at=datetime.datetime.now(UTC),
        ),
    )


def shipments_from_gls(response: dict) -> PaginatedResult[Shipment]:
    """Map a GLS GetParcelList response to PaginatedResult[Shipment]."""
    data_list = response.get("PrintDataInfoList", [])
    shipments = [_build_shipment_from_parcel_entry(entry) for entry in data_list]

    return PaginatedResult(
        items=shipments,
        cursor=None,
        has_more=False,
        total=len(shipments),
    )


# ── Shipment request builder ──


def build_awb_payload(shipment: Shipment, client_number: int) -> dict:
    """
    Build a GLS PrintLabels parcel payload from a normalized Shipment DTO.

    Args:
        shipment: The shipment to generate an AWB for.
        client_number: GLS client number.
    """
    recipient = shipment.recipient
    sender = shipment.sender
    parcels = shipment.parcels or [Parcel(weight=1.0)]

    payload: dict = {
        "ClientNumber": client_number,
        "ClientReference": shipment.extra.get("client_reference", "") if shipment.extra else "",
        "Count": len(parcels),
    }

    if recipient:
        payload["DeliveryAddress"] = {
            "Name": recipient.extra.get("name", ""),
            "Street": recipient.street,
            "City": recipient.city,
            "ZipCode": recipient.postal_code,
            "CountryIsoCode": recipient.country or "RO",
            "ContactName": recipient.extra.get("contact_name", recipient.extra.get("name", "")),
            "ContactPhone": recipient.extra.get("phone", ""),
            "ContactEmail": recipient.extra.get("email", ""),
        }

    if sender:
        payload["PickupAddress"] = {
            "Name": sender.extra.get("name", ""),
            "Street": sender.street,
            "City": sender.city,
            "ZipCode": sender.postal_code,
            "CountryIsoCode": sender.country or "RO",
            "ContactName": sender.extra.get("contact_name", sender.extra.get("name", "")),
            "ContactPhone": sender.extra.get("phone", ""),
            "ContactEmail": sender.extra.get("email", ""),
        }

    # COD
    if shipment.extra:
        if shipment.extra.get("cod_amount"):
            payload["CODAmount"] = shipment.extra["cod_amount"]
            payload["CODReference"] = shipment.extra.get("cod_reference", "")
            payload["CODCurrency"] = shipment.extra.get("cod_currency", "RON")
        if "content" in shipment.extra:
            payload["Content"] = shipment.extra["content"]
        if "service_list" in shipment.extra:
            payload["ServiceList"] = shipment.extra["service_list"]
        if "pickup_date" in shipment.extra:
            payload["PickupDate"] = shipment.extra["pickup_date"]

    return payload
