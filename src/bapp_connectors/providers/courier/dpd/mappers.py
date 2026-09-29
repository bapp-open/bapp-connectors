"""DPD Romania <-> DTO mappers."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime

from bapp_connectors.core.dto import Address, AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent

# Operation codes (reference, Appendix 1). Final per DPD: -14, 124, 125, 127, 128, 129.
DPD_OPERATION_MAP: dict[int, ShipmentStatus] = {
    148: ShipmentStatus.CREATED,  # shipment data received
    39: ShipmentStatus.PICKED_UP,
    12: ShipmentStatus.OUT_FOR_DELIVERY,
    134: ShipmentStatus.OUT_FOR_DELIVERY,  # ready at an office / locker
    -14: ShipmentStatus.DELIVERED,
    44: ShipmentStatus.FAILED_DELIVERY,
    123: ShipmentStatus.FAILED_DELIVERY,  # refused by recipient
    190: ShipmentStatus.FAILED_DELIVERY,  # bad address
    111: ShipmentStatus.RETURNED,  # return to sender (in progress)
    124: ShipmentStatus.RETURNED,  # delivered back to sender
    128: ShipmentStatus.CANCELLED,
    125: ShipmentStatus.CANCELLED,  # destroyed
    127: ShipmentStatus.CANCELLED,  # theft
    129: ShipmentStatus.CANCELLED,  # administrative closure
}

_STREET_PREFIX = re.compile(
    r"^\s*(str(ada)?|b(ule)?v(ar)?d?|bd|sos(eaua)?|sh|cal(ea)?|al(eea)?|spl(aiul)?|pta|piata|intr(area)?|drum(ul)?)\.?\s+",
    re.IGNORECASE,
)
_TRAILING_NUMBER = re.compile(r"[\s,]+(nr\.?\s*)?(\d+[a-zA-Z]?)\s*$", re.IGNORECASE)


def map_operation(code) -> ShipmentStatus:
    try:
        return DPD_OPERATION_MAP.get(int(code), ShipmentStatus.IN_TRANSIT)
    except (TypeError, ValueError):
        return ShipmentStatus.IN_TRANSIT


def plain(text) -> str:
    """DPD transliterates outside Windows-1251; send Romanian text without diacritics."""
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().strip()


def split_street(street: str, number: str = "") -> tuple[str, str]:
    """('Str. Lunga 3', '') -> ('Lunga', '3'): the bare name to search, and the number."""
    street = plain(street)
    if not number:
        match = _TRAILING_NUMBER.search(street)
        if match:
            number, street = match.group(2), street[: match.start()]
    return _STREET_PREFIX.sub("", street).strip(" ,"), plain(number)


def phone(value) -> str:
    digits = re.sub(r"[^\d+]", "", str(value or ""))
    return digits[:20]


def build_recipient(recipient: Address, site_id: int | None, street_id: int | None, street_no: str) -> dict:
    extra = recipient.extra or {}
    company = plain(extra.get("company"))
    person = plain(extra.get("contact_name") or extra.get("name"))
    body: dict = {
        "phone1": {"number": phone(extra.get("phone"))},
        "privatePerson": not company,
        "clientName": (company or person)[:60],
        "email": str(extra.get("email") or "")[:255],
    }
    if company and person:
        body["contactName"] = person[:60]  # forbidden for private persons, required for companies
    if extra.get("pickup_point_id"):  # office / locker (APT)
        body["pickupOfficeId"] = int(extra["pickup_point_id"])
        return body
    address: dict = {"countryId": 642}
    if site_id:
        address["siteId"] = site_id
    else:
        address.update({"siteName": plain(recipient.city)[:50], "postCode": str(recipient.postal_code or "")[:10]})
    for key, field, limit in (("block", "blockNo", 32), ("entrance", "entranceNo", 10), ("floor", "floorNo", 10),
                              ("flat", "apartmentNo", 10)):
        if extra.get(key):
            address[field] = plain(extra[key])[:limit]
    if street_id and (street_no or address.get("blockNo")):
        address["streetId"] = street_id
        if street_no:
            address["streetNo"] = street_no[:10]
    else:
        # unmatched street: the whole text goes to addressNote (manual processing at DPD)
        address["addressNote"] = plain(f"{recipient.street} {extra.get('number') or ''}")[:200]
    body["address"] = address
    return body


def build_shipment_body(shipment: Shipment, recipient: dict, sender_client_id: str, service_id: int,
                        payer: str, package: str) -> dict:
    extra = shipment.extra or {}
    parcels = shipment.parcels or [Parcel(weight=1.0)]
    additional: dict = {}
    if extra.get("cod_amount"):
        additional["cod"] = {"amount": round(float(extra["cod_amount"]), 2), "currencyCode": "RON",
                             "processingType": "CASH"}
    if extra.get("declared_value"):
        additional["declaredValue"] = {"amount": round(float(extra["declared_value"]), 2),
                                       "fragile": bool(extra.get("fragile"))}
    body: dict = {
        "recipient": recipient,
        "service": {"serviceId": int(extra.get("service") or service_id), "autoAdjustPickupDate": True},
        "content": {
            "contents": plain(extra.get("content") or "Colet")[:100],
            "package": package[:50],
            "parcels": [
                {"seqNo": i, "weight": round(max(p.weight or 1.0, 0.1), 2),
                 **({"size": {"width": math.ceil(p.width), "depth": math.ceil(p.length), "height": math.ceil(p.height)}}
                    if p.width and p.length and p.height else {})}
                for i, p in enumerate(parcels, start=1)
            ],
        },
        "payment": {"courierServicePayer": payer},
        "ref1": plain(extra.get("reference") or extra.get("content") or "")[:30],
    }
    if additional:
        body["service"]["additionalServices"] = additional
    if extra.get("uit_code"):
        body["content"]["uitCode"] = extra["uit_code"]
    if extra.get("observation"):
        body["shipmentNote"] = plain(extra["observation"])[:200]
    if sender_client_id:
        body["sender"] = {"clientId": int(sender_client_id)}
    return body


def awb_label_from_dpd(response: dict, pdf: bytes | None) -> AWBLabel:
    price = response.get("price") or {}
    return AWBLabel(
        tracking_number=str(response.get("id") or ""),
        label_pdf=pdf,
        cost=price.get("total"),
        extra={"parcel_ids": [str(p.get("id")) for p in response.get("parcels") or []],
               "pickup_date": response.get("pickupDate"), "delivery_deadline": response.get("deliveryDeadline"),
               "currency": price.get("currency")},
    )


def _parse_dt(value) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except (TypeError, ValueError):
            continue
    return None


def tracking_events_from_dpd(parcel: dict) -> list[TrackingEvent]:
    events = [
        TrackingEvent(
            status=map_operation(op.get("operationCode")),
            description=op.get("description") or "",
            location=op.get("place") or "",
            timestamp=_parse_dt(op.get("dateTime")),
            extra={"code": op.get("operationCode"), "return_awb": op.get("returnShipmentId"),
                   "exceptions": op.get("exceptionCodes") or []},
        )
        for op in parcel.get("operations") or []
    ]
    return sorted(events, key=lambda e: e.timestamp.timestamp() if e.timestamp else 0)
