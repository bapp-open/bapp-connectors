"""Cargus <-> DTO mappers."""

from __future__ import annotations

import math
from datetime import datetime

from bapp_connectors.core.dto import AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent

PUDO_SERVICE_ID = 38

# Event ids — Cargus publishes no list. 21 = delivered is corroborated by two
# integrations; the rest come from one open-source adapter (see README).
_DELIVERED = {21, 60, 64, 146}
_REFUSED = {153, 158, 159, 161, 180, 181, 182, 185, 186, 96, 54}
_RETURNED = {196, 197, 198}
_PICKED_UP = {234, 70, 72, 73}
_OUT_FOR_DELIVERY = {5}


def map_event(event_id) -> ShipmentStatus:
    try:
        code = int(event_id)
    except (TypeError, ValueError):
        return ShipmentStatus.IN_TRANSIT
    if code in _DELIVERED:
        return ShipmentStatus.DELIVERED
    if code in _RETURNED:
        return ShipmentStatus.RETURNED
    if code in _REFUSED:
        return ShipmentStatus.FAILED_DELIVERY
    if code in _PICKED_UP:
        return ShipmentStatus.PICKED_UP
    if code in _OUT_FOR_DELIVERY:
        return ShipmentStatus.OUT_FOR_DELIVERY
    if code == 89:  # destroyed / abandoned with the sender's agreement
        return ShipmentStatus.CANCELLED
    return ShipmentStatus.IN_TRANSIT


def _cut(value, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def build_awb_body(shipment: Shipment, location_id: int, service_id: int, payer: int, cod_to_bank: bool) -> dict:
    """AwbTurModel. The recipient goes by names (ids 0), as the official plugin sends it."""
    extra = shipment.extra or {}
    recipient = shipment.recipient
    rex = recipient.extra or {}
    parcels = shipment.parcels or [Parcel(weight=1.0)]
    envelope = extra.get("package_type") == "envelope"
    pudo = rex.get("pickup_point_id")
    cod = round(float(extra.get("cod_amount") or 0), 2)
    name = rex.get("company") or rex.get("name") or ""
    number = _cut(rex.get("number"), 20)
    address_text = " ".join(filter(None, [recipient.street, number and f"nr. {number}",
                                           rex.get("block") and f"bl. {rex['block']}",
                                           rex.get("entrance") and f"sc. {rex['entrance']}",
                                           rex.get("floor") and f"et. {rex['floor']}",
                                           rex.get("flat") and f"ap. {rex['flat']}"]))
    body: dict = {
        "Sender": {"LocationId": location_id},
        "Recipient": {
            "LocationId": 0,
            "Name": _cut(name, 100),
            "CountyId": 0,
            "CountyName": _cut(recipient.region, 100),
            "LocalityId": 0,
            "LocalityName": _cut(recipient.city, 100),
            "StreetId": 0,
            "StreetName": _cut(recipient.street, 100),
            "BuildingNumber": number,
            "AddressText": _cut(address_text),
            "ContactPerson": _cut(rex.get("contact_name") or rex.get("name") or name, 100),
            "PhoneNumber": "".join(ch for ch in str(rex.get("phone") or "") if ch.isdigit() or ch == "+"),
            "Email": _cut(rex.get("email"), 100),
            "CodPostal": _cut(recipient.postal_code, 10),
        },
        "Parcels": 0 if envelope else len(parcels),
        "Envelopes": len(parcels) if envelope else 0,
        "TotalWeight": 1 if envelope else max(1, math.ceil(sum(p.weight or 0 for p in parcels) or 1)),
        "ServiceId": PUDO_SERVICE_ID if pudo else int(extra.get("service") or service_id),
        "DeclaredValue": round(float(extra.get("declared_value") or 0), 2),
        "CashRepayment": 0 if cod_to_bank else cod,
        "BankRepayment": cod if cod_to_bank else 0,
        "OtherRepayment": "",
        "OpenPackage": bool(extra.get("open_package")),
        "ShipmentPayer": payer,
        "SaturdayDelivery": bool(extra.get("saturday_delivery")),
        "MorningDelivery": False,
        "Observations": _cut(extra.get("observation")),
        "PackageContent": _cut(extra.get("content")),
        "CustomString": _cut(extra.get("reference") or extra.get("content"), 50),
        "ParcelCodes": [
            {"Code": "0", "Type": 0 if envelope else 1, "Weight": round(p.weight or 1.0, 2),
             "Length": math.ceil(p.length or 10), "Width": math.ceil(p.width or 10), "Height": math.ceil(p.height or 10),
             "ParcelContent": _cut(p.reference or extra.get("content"), 100)}
            for p in parcels
        ],
    }
    if pudo:
        # Ship & Go point: no cash on delivery, no street, no open package (official plugin)
        body["DeliveryPudoPoint"] = int(pudo)
        body["CashRepayment"] = 0
        body["OpenPackage"] = False
    return body


def awb_label_from_cargus(awb: dict, pdf: bytes | None) -> AWBLabel:
    cost = (awb.get("ShippingCost") or {}).get("GrandTotal")
    return AWBLabel(
        tracking_number=str(awb.get("BarCode") or ""),
        label_pdf=pdf,
        cost=float(cost) if cost is not None else None,
        extra={"parcel_codes": [str(p.get("Code")) for p in awb.get("ParcelCodes") or [] if p.get("Code")],
               "return_awb": awb.get("ReturnAwb") or "", "return_code": awb.get("ReturnCode") or ""},
    )


def _parse_dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def tracking_events_from_cargus(trace: dict) -> list[TrackingEvent]:
    events = [
        TrackingEvent(
            status=map_event(e.get("EventId")),
            description=e.get("Description") or "",
            location=e.get("LocalityName") or "",
            timestamp=_parse_dt(e.get("Date")),
            extra={"code": e.get("EventId")},
        )
        for e in trace.get("Event") or []
    ]
    return sorted(events, key=lambda e: e.timestamp.timestamp() if e.timestamp else 0)


def shipment_from_cargus(awb: dict) -> Shipment:
    return Shipment(
        tracking_number=str(awb.get("BarCode") or ""),
        carrier="cargus",
        parcels=[Parcel(weight=float(awb.get("TotalWeight") or 0))],
        extra={"status": awb.get("Status", ""), "service": awb.get("ServiceId"),
               "reference": awb.get("CustomString", ""), "cod": awb.get("BankRepayment") or awb.get("CashRepayment"),
               "cost": (awb.get("ShippingCost") or {}).get("GrandTotal")},
    )
