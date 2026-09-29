"""eColet <-> DTO mappers."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from bapp_connectors.core.dto import Address, AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent

# Normalized status slugs the panel shows (no official list): see README.
ECOLET_STATUS_MAP: dict[str, ShipmentStatus] = {
    "new": ShipmentStatus.CREATED,
    "received": ShipmentStatus.PICKED_UP,
    "delivering": ShipmentStatus.OUT_FOR_DELIVERY,
    "delivered": ShipmentStatus.DELIVERED,
    "avizat": ShipmentStatus.FAILED_DELIVERY,
    "redirect": ShipmentStatus.IN_TRANSIT,
    "exception": ShipmentStatus.FAILED_DELIVERY,
    "deposit": ShipmentStatus.IN_TRANSIT,
    "canceled": ShipmentStatus.CANCELLED,
    "return": ShipmentStatus.RETURNED,
    "returned": ShipmentStatus.RETURNED,
    "delivered to sender": ShipmentStatus.RETURNED,
}


def map_status(slug: str) -> ShipmentStatus:
    return ECOLET_STATUS_MAP.get((slug or "").strip().lower(), ShipmentStatus.IN_TRANSIT)


def _cut(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_party(address: Address, locality_id: int | None) -> dict:
    """Sender/receiver block. `address.extra` carries name/phone/email/number and
    optionally company, block, entrance, floor, flat, map_point_id (locker)."""
    extra = address.extra or {}
    name = extra.get("company") or extra.get("name") or ""
    party = {
        "name": _cut(name, 60),
        "country": (address.country or "RO").lower(),
        "county": address.region,
        "locality_id": locality_id,
        "locality": _cut(address.city, 100),
        "postal_code": _cut(address.postal_code, 100),
        "street_name": _cut(address.street, 50),
        "street_number": _cut(extra.get("number"), 10),
        "block": _cut(extra.get("block"), 10) or None,
        "entrance": _cut(extra.get("entrance"), 10) or None,
        "floor": _cut(extra.get("floor"), 10) or None,
        "flat": _cut(extra.get("flat"), 10) or None,
        "contact_person": _cut(extra.get("contact_name") or extra.get("name") or name, 60),
        "email": _cut(extra.get("email"), 150),
        "phone": "".join(ch for ch in str(extra.get("phone") or "") if ch.isdigit() or ch == "+")[:15],
        "has_map_point": bool(extra.get("map_point_id")),
    }
    if extra.get("map_point_id"):
        party["map_point_id"] = int(extra["map_point_id"])
    return party


def build_order_body(
    shipment: Shipment,
    sender: dict,
    receiver: dict,
    service: str = "",
    pickup: dict | None = None,
) -> dict:
    """v2 order body (multipack): `parcel` keeps type/shape, `parcels` one item per package.

    eColet takes whole kg and cm (minimum 1), so fractions are rounded up.
    """
    extra = shipment.extra or {}
    parcels = shipment.parcels or [Parcel(weight=1.0)]
    declared = extra.get("declared_value")
    per_parcel_declared = round(float(declared) / len(parcels), 2) if declared else None
    body: dict = {
        "sender": sender,
        "receiver": receiver,
        "parcel": {
            "type": extra.get("package_type", "package"),
            "shape": "standard",
            "content": _cut(extra.get("content") or "Colet", 255),
            "observations": _cut(extra.get("observation"), 255) or None,
        },
        "parcels": [
            {
                "weight": max(1, math.ceil(p.weight or 1)),
                "dimensions": {
                    "length": max(1, math.ceil(p.length or 10)),
                    "width": max(1, math.ceil(p.width or 10)),
                    "height": max(1, math.ceil(p.height or 10)),
                },
                "declared_value": per_parcel_declared,
                "content": _cut(p.reference or extra.get("content") or "Colet", 255),
            }
            for p in parcels
        ],
        "additional_services": {
            "cod": {"status": bool(extra.get("cod_amount")), "amount": float(extra.get("cod_amount") or 0) or None},
            "open_package": {"status": bool(extra.get("open_package"))},
            "saturday_delivery": {"status": bool(extra.get("saturday_delivery"))},
            "sms_notify": {"status": bool(extra.get("sms_notify"))},
        },
        "courier": {"service": service, "pickup": pickup or {"type": "courier"}},
    }
    if extra.get("uit_code"):
        body["shipment_details"] = {"uit_code": extra["uit_code"]}
    return body


def choose_service(form: dict, preferred: str = "") -> str:
    """The preferred slug if eColet offers it for this shipment, else the cheapest one offered."""
    available = [slug for slug, ok in (form.get("statuses") or {}).items() if ok]
    if preferred:
        if preferred in available:
            return preferred
        raise ValueError(f"eColet service {preferred!r} is not available for this shipment; available: {available}")
    if not available:
        errors = form.get("errors") or {}
        raise ValueError(f"eColet offers no service for this shipment. {errors or ''}".strip())
    prices = form.get("prices_gross") or {}
    return min(available, key=lambda slug: _price(prices.get(slug)))


def pickup_slot(form: dict, service: str, pickup_type: str = "courier") -> dict:
    if pickup_type == "self":
        return {"type": "self"}
    slot = (form.get("pickup_dates") or {}).get(service) or {}
    hours = slot.get("hours") or []
    return {"type": "courier", "date": slot.get("date"), "time": hours[0] if hours else None}


def _price(value) -> float:
    try:
        return float(str(value).replace(".", "").replace(",", ".")) if value not in (None, "") else math.inf
    except ValueError:
        return math.inf


def awb_label_from_ecolet(order: dict, pdf: bytes | None, order_to_send_id: int) -> AWBLabel:
    service = order.get("service") or {}
    return AWBLabel(
        tracking_number=str(order.get("awb") or ""),
        label_pdf=pdf,
        cost=order.get("price"),
        extra={
            "order_id": order.get("id"),
            "order_to_send_id": order_to_send_id,
            "service": service.get("slug", ""),
            "courier": service.get("courier_slug", ""),
            "courier_name": service.get("courier_name", ""),
            "waybill_extension": order.get("waybill_extension", ""),
        },
    )


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def tracking_events_from_ecolet(entry: dict) -> list[TrackingEvent]:
    """Events oldest first, like the other couriers."""
    events = [
        TrackingEvent(
            status=map_status(item.get("name", "")),
            description=item.get("real_name") or item.get("name", ""),
            timestamp=_parse_dt(item.get("created_at")),
            extra={"slug": item.get("name", "")},
        )
        for item in entry.get("statuses") or []
    ]
    return sorted(events, key=lambda e: e.timestamp or datetime.min.replace(tzinfo=UTC))


def shipment_from_ecolet(order: dict) -> Shipment:
    service = order.get("service") or {}
    return Shipment(
        tracking_number=str(order.get("awb") or ""),
        status=map_status(order.get("status", "")),
        carrier=service.get("courier_slug", "") or "ecolet",
        parcels=[Parcel(weight=float(order.get("weight") or 0))],
        extra={"order_id": order.get("id"), "service": service.get("slug", ""), "price": order.get("price"),
               "cod": order.get("cod")},
    )
