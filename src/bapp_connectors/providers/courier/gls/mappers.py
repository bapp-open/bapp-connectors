"""
GLS <-> DTO mappers.

Converts between raw GLS API payloads and normalized framework DTOs.
This is the boundary between provider-specific data and the unified domain model.
"""

from __future__ import annotations

import contextlib
import datetime
import re
from dataclasses import dataclass
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
from bapp_connectors.core.errors import ValidationError

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

# Dialling codes for the GLS countries; SMS services want the number in international format
_DIAL_CODES = {"RO": "40", "HU": "36", "HR": "385", "CZ": "420", "SI": "386", "SK": "421", "RS": "381"}
# national (trunk) prefix dropped when going international; "0" elsewhere, none in CZ
_TRUNK_PREFIX = {"HU": "06", "CZ": ""}
# COD currency when the shipment does not say: the destination country's currency
_COD_CURRENCY = {"RO": "RON", "HU": "HUF", "HR": "EUR", "CZ": "CZK", "SI": "EUR", "SK": "EUR", "RS": "RSD"}

_GLS_DATE = re.compile(r"/Date\((-?\d+)(?:([+-])(\d{2})(\d{2}))?\)/")


def _map_gls_status(status_code: str) -> ShipmentStatus:
    """Map a GLS status code to a normalized ShipmentStatus."""
    return GLS_STATUS_MAP.get(status_code, ShipmentStatus.IN_TRANSIT)


def _parse_gls_date(value: str) -> datetime.datetime | None:
    """
    Parse GLS date format: /Date(1739142000000+0100)/

    The number is milliseconds since the epoch (UTC); the optional offset is the zone the
    moment was recorded in, kept on the returned (aware) datetime.
    """
    if not value:
        return None
    match = _GLS_DATE.search(value)
    if not match:
        return None
    millis, sign, hours, minutes = match.groups()
    tz = UTC
    if sign:
        offset = datetime.timedelta(hours=int(hours), minutes=int(minutes))
        tz = datetime.timezone(-offset if sign == "-" else offset)
    return datetime.datetime.fromtimestamp(int(millis) / 1000, tz=tz)


def international_phone(phone: str, country: str = "RO") -> str:
    """`0722 123 456` -> `+40722123456`; numbers already international are only cleaned."""
    raw = (phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    country = (country or "RO").upper()
    dial = _DIAL_CODES.get(country, "")
    trunk = _TRUNK_PREFIX.get(country, "0")
    if dial and digits.startswith(dial) and not digits.startswith("0"):
        return "+" + digits
    if dial and digits.startswith(trunk):
        return f"+{dial}{digits[len(trunk):]}"
    return digits


def as_bool(value) -> bool:
    return value not in (None, False, "", "false", "False", "0", 0)


# ── AWB label mapper ──


def awb_label_from_gls(data: dict) -> AWBLabel:
    """Map a GLS PrintLabels response to an AWBLabel DTO."""
    info_list = data.get("PrintLabelsInfoList") or []
    errors = data.get("PrintLabelsErrorList") or []

    tracking_number = ""
    parcel_id = 0
    if info_list:
        first = info_list[0]
        tracking_number = str(first.get("ParcelNumber") or "")
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
            "parcel_numbers": [str(p.get("ParcelNumber")) for p in info_list if p.get("ParcelNumber")],
            "errors": errors,
        },
        provider_meta=ProviderMeta(
            provider="gls",
            raw_id=tracking_number,
            raw_payload={k: v for k, v in data.items() if k != "Labels"},
            fetched_at=datetime.datetime.now(UTC),
        ),
    )


# ── Tracking mapper ──


def tracking_events_from_gls(data: dict) -> list[TrackingEvent]:
    """Map a GLS `ParcelStatusList` (GetParcelStatuses, or one entry of GetParcelListStatuses)
    to TrackingEvents, oldest first.

    GLS lists the newest status first; callers take the last event as the current state."""
    events: list[TrackingEvent] = []
    for entry in data.get("ParcelStatusList") or []:
        status_code = str(entry.get("StatusCode") or "")
        events.append(
            TrackingEvent(
                status=_map_gls_status(status_code),
                description=entry.get("StatusDescription") or "",
                location=entry.get("DepotCity") or "",
                timestamp=_parse_gls_date(entry.get("StatusDate") or ""),
                extra={
                    "code": status_code,
                    "status_code": status_code,
                    "status_info": entry.get("StatusInfo") or "",
                    "depot_number": entry.get("DepotNumber") or "",
                },
            )
        )
    # reversed first so events with the same (or no) timestamp keep GLS' order, oldest first
    events.reverse()
    events.sort(key=lambda e: e.timestamp or datetime.datetime.min.replace(tzinfo=UTC))
    return events


def tracking_batch_from_gls(data: dict) -> dict[str, list[TrackingEvent]]:
    """Map a GetParcelListStatuses response to {parcel number: events, oldest first}."""
    return {
        str(entry.get("ParcelNumber")): tracking_events_from_gls(entry)
        for entry in data.get("ParcelList") or []
        if entry.get("ParcelNumber")
    }


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


@dataclass(frozen=True)
class GLSServiceSettings:
    """Account-wide notification services, from the connection settings."""

    sms: bool = False           # SM1: SMS when the parcel is handed over, with a custom text
    sms_text: str = ""
    sms_preadvice: bool = False  # SM2: SMS on the delivery day
    flex_delivery: bool = False  # FDS: e-mail with the delivery window and options
    flex_delivery_sms: bool = False  # FSS: FDS by SMS (only together with FDS)

    @classmethod
    def from_config(cls, config: dict) -> GLSServiceSettings:
        return cls(
            sms=as_bool(config.get("service_sm1")),
            sms_text=str(config.get("service_sm1_text") or "").strip(),
            sms_preadvice=as_bool(config.get("service_sm2")),
            flex_delivery=as_bool(config.get("service_fds")),
            flex_delivery_sms=as_bool(config.get("service_fss")),
        )

    def validate(self) -> None:
        if self.sms and not self.sms_text:
            raise ValidationError("GLS: the SMS service (SM1) needs the SMS text in the connection settings.")
        if self.flex_delivery_sms and not self.flex_delivery:
            raise ValidationError("GLS: FlexDeliverySMS (FSS) works only together with FlexDelivery (FDS).")


def _house_number(value) -> str:
    """GLS takes digits only in HouseNumber and refuses 0 (error 23)."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if digits.strip("0") else ""


def _gls_address(address: Address, default_email: str = "") -> dict:
    extra = address.extra or {}
    country = (address.country or "RO").upper()
    name = extra.get("company") or extra.get("name") or extra.get("contact_name") or ""
    payload = {
        "Name": name,
        "Street": address.street,
        "City": address.city,
        "ZipCode": address.postal_code,
        "CountryIsoCode": country,
        "ContactName": extra.get("contact_name") or extra.get("name") or name,
        "ContactPhone": international_phone(extra.get("phone", ""), country),
        "ContactEmail": extra.get("email") or default_email,
    }
    if number := _house_number(extra.get("number")):
        payload["HouseNumber"] = number
    if info := extra.get("house_number_info"):
        payload["HouseNumberInfo"] = str(info)
    return payload


def _parcel_properties(parcels: list[Parcel], content: str) -> list[dict]:
    properties = []
    for parcel in parcels:
        prop: dict = {}
        if parcel.weight:
            prop["Weight"] = round(float(parcel.weight), 2)
        for gls_name, value in (("Length", parcel.length), ("Width", parcel.width), ("Height", parcel.height)):
            if value:
                prop[gls_name] = round(float(value))
        if prop:
            if content:
                prop["Content"] = content
            properties.append(prop)
    return properties


def _notification_services(delivery: dict, settings: GLSServiceSettings) -> list[dict]:
    phone = delivery.get("ContactPhone") or ""
    email = delivery.get("ContactEmail") or ""
    services = []
    if settings.sms and phone and settings.sms_text:
        services.append({"Code": "SM1", "SM1Parameter": {"Value": f"{phone}|{settings.sms_text}"}})
    if settings.sms_preadvice and phone:
        services.append({"Code": "SM2", "SM2Parameter": {"Value": phone}})
    if settings.flex_delivery and email:
        services.append({"Code": "FDS", "FDSParameter": {"Value": email}})
        # FSS without FDS is refused (error 30), so it follows FDS, not the setting alone
        if settings.flex_delivery_sms and phone:
            services.append({"Code": "FSS", "FSSParameter": {"Value": phone}})
    return services


def _parcel_shop_service(pickup_point_id, delivery: dict) -> dict:
    """PSD: delivery to a ParcelShop / ParcelLocker; GLS then requires the full recipient contact."""
    missing = [f for f in ("ContactName", "ContactPhone", "ContactEmail") if not delivery.get(f)]
    if missing:
        raise ValidationError(f"GLS: delivery to a ParcelShop/locker needs the recipient's {', '.join(missing)}.")
    point = str(pickup_point_id).strip()
    # DeliveryPoint.Id (numeric) goes in IntegerValue; a matchcode ("2351-CSOMAGPONT") in StringValue
    parameter = {"IntegerValue": int(point)} if point.isdigit() else {"StringValue": point}
    return {"Code": "PSD", "PSDParameter": parameter}


def build_awb_payload(
    shipment: Shipment,
    client_number: int,
    services: GLSServiceSettings | None = None,
) -> dict:
    """
    Build a GLS PrintLabels parcel payload from a normalized Shipment DTO.

    Args:
        shipment: The shipment to generate an AWB for.
        client_number: GLS client number.
        services: Account-wide notification services (connection settings).
    """
    services = services or GLSServiceSettings()
    services.validate()
    if not shipment.recipient:
        raise ValidationError("GLS needs the recipient address.")
    if not shipment.sender:
        raise ValidationError("GLS needs the pickup (sender) address.")

    extra = shipment.extra or {}
    parcels = shipment.parcels or [Parcel(weight=1.0)]
    if len(parcels) > 99:
        raise ValidationError("GLS accepts at most 99 parcels in one shipment.")
    reference = str(extra.get("reference") or extra.get("client_reference") or "")
    content = str(extra.get("content") or reference)

    delivery = _gls_address(shipment.recipient)
    payload: dict = {
        "ClientNumber": client_number,
        "ClientReference": reference,
        "Count": len(parcels),
        "Content": content,
        "PickupAddress": _gls_address(shipment.sender, default_email=extra.get("sender_email", "")),
        "DeliveryAddress": delivery,
    }

    service_list: list[dict] = []

    cod_amount = float(extra.get("cod_amount") or 0)
    if cod_amount > 0:
        payload["CODAmount"] = round(cod_amount, 2)
        payload["CODReference"] = str(extra.get("cod_reference") or reference)
        payload["CODCurrency"] = extra.get("cod_currency") or _COD_CURRENCY.get(delivery["CountryIsoCode"], "RON")
        service_list.append({"Code": "COD"})

    if pickup_point_id := (shipment.recipient.extra or {}).get("pickup_point_id"):
        service_list.append(_parcel_shop_service(pickup_point_id, delivery))

    service_list += _notification_services(delivery, services)

    # raw GLS services from the caller (e.g. [{"Code": "SAT"}]); a code already set above is not repeated
    codes = {s["Code"] for s in service_list}
    service_list += [s for s in extra.get("service_list") or [] if s.get("Code") not in codes]
    payload["ServiceList"] = service_list

    if properties := _parcel_properties(parcels, content):
        payload["ParcelPropertyList"] = properties

    if pickup_date := extra.get("pickup_date"):
        if isinstance(pickup_date, datetime.date):
            if not isinstance(pickup_date, datetime.datetime):
                pickup_date = datetime.datetime.combine(pickup_date, datetime.time(12))
            pickup_date = f"/Date({int(pickup_date.timestamp() * 1000)})/"
        payload["PickupDate"] = pickup_date

    return payload
