"""FAN Courier <-> DTO mappers."""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from bapp_connectors.core.dto import AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent

_BUCHAREST = ZoneInfo("Europe/Bucharest")

# Service -> its "Cont Colector" variant (cash on delivery wired to the sender's bank
# account instead of travelling back on a reimbursement AWB). Names from /reports/services.
CONT_COLECTOR_VARIANT = {
    "Standard": "Cont Colector",
    "RedCode": "Red code-Cont Colector",
    "Express Loco 1H": "Express Loco 1H-Cont Colector",
    "Express Loco 2H": "Express Loco 2H-Cont Colector",
    "Express Loco 4H": "Express Loco 4H-Cont Colector",
    "Express Loco 6H": "Express Loco 6H-Cont Colector",
    "Export": "Export-Cont Colector",
    "CollectPoint": "CollectPoint Cont Colector",
    "Produse Albe": "Produse Albe-Cont Colector",
    "Transport Marfa": "Transport Marfa-Cont Colector",
    "Transport Marfa Produse Albe": "Transport Marfa Produse Albe-Cont Colector",
    "FANbox": "FANbox Cont Colector",
}

# Event codes (/reports/awb-events). The docs do not classify them; see README.
FAN_EVENT_MAP: dict[str, ShipmentStatus] = {
    "C0": ShipmentStatus.PICKED_UP,
    "C1": ShipmentStatus.OUT_FOR_DELIVERY,
    "S1": ShipmentStatus.OUT_FOR_DELIVERY,
    "S2": ShipmentStatus.DELIVERED,
    "S8": ShipmentStatus.OUT_FOR_DELIVERY,  # delivery from a FAN office
    "S46": ShipmentStatus.OUT_FOR_DELIVERY,  # left at a delivery point / locker, awaiting pickup
    "S6": ShipmentStatus.FAILED_DELIVERY,  # refused
    "S7": ShipmentStatus.FAILED_DELIVERY,  # transport payment refused
    "S12": ShipmentStatus.FAILED_DELIVERY,  # later delivery
    "S15": ShipmentStatus.FAILED_DELIVERY,  # cash on delivery refused
    "S33": ShipmentStatus.FAILED_DELIVERY,  # return requested
    "S16": ShipmentStatus.RETURNED,  # returned after the holding period
    "S43": ShipmentStatus.RETURNED,
    "S38": ShipmentStatus.CREATED,  # AWB not handed over
}


def map_event(code: str) -> ShipmentStatus:
    code = (code or "").strip().upper()
    if code in FAN_EVENT_MAP:
        return FAN_EVENT_MAP[code]
    return ShipmentStatus.IN_TRANSIT  # hub scans (H*) and anything new


def resolve_service(service: str, cod_amount: float, cod_to_bank_account: bool) -> str:
    if cod_amount and cod_to_bank_account and "Cont Colector" not in service:
        return CONT_COLECTOR_VARIANT.get(service, service)
    return service


def _cut(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _phone(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch == "+")[:16]


def build_awb_body(shipment: Shipment, client_id: str, service: str, payer: str) -> dict:
    """One shipment for POST /intern-awb. Weight in kg, dimensions in cm (whole numbers)."""
    extra = shipment.extra or {}
    recipient = shipment.recipient
    rex = recipient.extra or {}
    parcels = shipment.parcels or [Parcel(weight=1.0)]
    envelope = extra.get("package_type") == "envelope"
    largest = max(parcels, key=lambda p: (p.length or 0) * (p.width or 0) * (p.height or 0))
    info = {
        "service": service,
        "packages": {"parcel": 0 if envelope else len(parcels), "envelope": len(parcels) if envelope else 0},
        "weight": max(1, math.ceil(sum(p.weight or 0 for p in parcels) or 1)),
        "cod": round(float(extra.get("cod_amount") or 0), 2),
        "declaredValue": round(float(extra.get("declared_value") or 0), 2),
        "payment": payer,
        "observation": _cut(extra.get("observation"), 255),
        "content": _cut(extra.get("content"), 255),
        "dimensions": {
            "length": max(1, math.ceil(largest.length or 10)),
            "height": max(1, math.ceil(largest.height or 10)),
            "width": max(1, math.ceil(largest.width or 10)),
        },
        "costCenter": _cut(extra.get("cost_center"), 40),
        "options": list(extra.get("options") or []),
    }
    if extra.get("uit_code"):
        info["uitCode"] = extra["uit_code"]
    name = rex.get("company") or rex.get("name") or ""
    address = {
        "county": _cut(recipient.region, 50),
        "locality": _cut(recipient.city, 50),
        "street": _cut(recipient.street, 255),
        "streetNo": _cut(rex.get("number"), 10),
        "zipCode": _cut(recipient.postal_code, 6),
        "building": _cut(rex.get("block"), 20),
        "entrance": _cut(rex.get("entrance"), 16),
        "floor": _cut(rex.get("floor"), 10),
        "apartment": _cut(rex.get("flat"), 10),
    }
    if rex.get("pickup_point_id"):  # FANbox / PayPoint / FAN office
        address["pickupLocationId"] = str(rex["pickup_point_id"])
    return {
        "clientId": int(client_id) if str(client_id).isdigit() else client_id,
        "shipments": [{
            "info": info,
            "recipient": {
                "name": _cut(name, 50),
                "contactPerson": _cut(rex.get("contact_name") or rex.get("name") or name, 50),
                "phone": _phone(rex.get("phone")),
                "email": _cut(rex.get("email"), 100),
                "address": address,
            },
        }],
    }


def awb_label_from_fan(result: dict, pdf: bytes | None) -> AWBLabel:
    tariff = result.get("tariff")
    return AWBLabel(
        tracking_number=str(result.get("awbNumber") or ""),
        label_pdf=pdf,
        cost=float(tariff) if tariff is not None else None,
        extra={k: result.get(k) for k in ("vat", "packages", "routingCode", "office", "estimatedDeliveryTime")},
    )


def result_errors(result: dict) -> str:
    errors = result.get("errors")
    if isinstance(errors, dict):
        return "; ".join(f"{k}: {v}" for k, v in errors.items())
    if isinstance(errors, list):
        return "; ".join(map(str, errors))
    return str(errors or "")


def _parse_dt(value) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=_BUCHAREST)
        except (TypeError, ValueError):
            continue
    return None


def tracking_events_from_fan(entry: dict) -> list[TrackingEvent]:
    """FAN lists events oldest first; a returnAwbNumber means the parcel went back."""
    events = [
        TrackingEvent(
            status=map_event(e.get("id", "")),
            description=(e.get("name") or "").strip(),
            location=(e.get("location") or "").strip(),
            timestamp=_parse_dt(e.get("date")),
            extra={"code": e.get("id", "")},
        )
        for e in entry.get("events") or []
    ]
    if entry.get("returnAwbNumber") and events and events[-1].status != ShipmentStatus.RETURNED:
        events.append(TrackingEvent(status=ShipmentStatus.RETURNED, description="Retur",
                                    timestamp=events[-1].timestamp,
                                    extra={"return_awb": str(entry["returnAwbNumber"])}))
    return events


def shipment_from_fan(item: dict) -> Shipment:
    info = item.get("info") or {}
    return Shipment(
        tracking_number=str(info.get("awbNumber") or ""),
        carrier="fancourier",
        parcels=[Parcel(weight=float(info.get("weight") or 0))],
        extra={"service": info.get("service", ""), "cod": info.get("cod"), "cost": info.get("cost"),
               "date": info.get("date"), "content": info.get("content", "")},
    )
