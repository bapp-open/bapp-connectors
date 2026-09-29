"""
eColet courier adapter — implements CourierPort.

Booking is asynchronous: send-order returns an order-to-send id, eColet books the
courier in the background, and the AWB appears on the order once it is placed.
`generate_awb` polls for it (setting `awb_wait_seconds`).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import AWBLabel, ConnectionTestResult, PaginatedResult, Shipment, TrackingEvent
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.ecolet.client import EcoletApiClient
from bapp_connectors.providers.courier.ecolet.manifest import ECOLET_LIVE_URL, ECOLET_STAGING_URL, manifest
from bapp_connectors.providers.courier.ecolet.mappers import (
    awb_label_from_ecolet,
    build_order_body,
    build_party,
    choose_service,
    pickup_slot,
    shipment_from_ecolet,
    tracking_events_from_ecolet,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import Address

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 2.0


class EcoletCourierAdapter(CourierPort):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._service = (config.get("service") or "").strip()
        self._pickup_type = config.get("pickup_type") or "courier"
        wait = config.get("awb_wait_seconds")
        self._awb_wait = 30 if wait in (None, "") else max(0, int(wait))  # 0 is a valid "don't wait"
        staging = str(credentials.get("staging", "false")).lower() in ("true", "1", "yes")
        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="ecolet")
        self.client = EcoletApiClient(
            http_client=http_client,
            base_url=ECOLET_STAGING_URL if staging else ECOLET_LIVE_URL,
            client_id=credentials.get("client_id", ""),
            client_secret=credentials.get("client_secret", ""),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.me()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        if user.get("block_shipment"):
            return ConnectionTestResult(success=False, message="eColet account is blocked from sending shipments.")
        return ConnectionTestResult(success=True, message=f"Connected as {user.get('email', '')}")

    # ── CourierPort ──

    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        if not shipment.recipient:
            raise ValidationError("eColet needs the recipient address.")
        sender_address = shipment.sender or self._default_sender()
        sender = build_party(sender_address, self._locality_id(sender_address))
        receiver = build_party(shipment.recipient, self._locality_id(shipment.recipient))

        preferred = (shipment.extra or {}).get("service") or self._service
        form = self.client.reload_form(build_order_body(shipment, sender, receiver))
        try:
            service = choose_service(form, preferred)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        body = build_order_body(shipment, sender, receiver, service, pickup_slot(form, service, self._pickup_type))
        order_to_send_id = self.client.send_order(body)

        order_id = self._wait_for_order(order_to_send_id)
        order = self.client.order(order_id)
        pdf = None
        try:
            content, content_type = self.client.download_waybill(order_id)
            pdf = content if content[:4] == b"%PDF" or "pdf" in content_type else None
        except ProviderError:
            logger.warning("eColet waybill download failed for order %s", order_id, exc_info=True)
        return awb_label_from_ecolet(order, pdf, order_to_send_id)

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        entries = self.client.statuses_by_awb([tracking_number])
        entry = next((e for e in entries if str(e.get("awb")) == str(tracking_number)), None)
        return tracking_events_from_ecolet(entry) if entry else []

    def cancel_shipment(self, tracking_number: str) -> bool:
        entries = self.client.statuses_by_awb([tracking_number])
        entry = next((e for e in entries if str(e.get("awb")) == str(tracking_number)), None)
        if not entry:
            return False
        try:
            self.client.cancel_order(int(entry["id"]))
        except ProviderError:
            logger.warning("eColet cancel failed for AWB %s", tracking_number, exc_info=True)
            return False
        return True

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        page = int(cursor) if cursor else 1
        date_from = since.strftime("%Y-%m-%d") if since else ""
        response = self.client.list_orders(page=page, date_from=date_from,
                                           date_to=time.strftime("%Y-%m-%d") if since else "")
        meta = response.get("meta") or {}
        items = [shipment_from_ecolet(o) for o in response.get("data") or []]
        has_more = int(meta.get("current_page") or page) < int(meta.get("last_page") or page)
        return PaginatedResult(items=items, cursor=str(page + 1) if has_more else None, has_more=has_more,
                               total=meta.get("total"))

    # ── Helpers ──

    def _wait_for_order(self, order_to_send_id: int) -> int:
        deadline = time.monotonic() + self._awb_wait
        while True:
            state = self.client.order_to_send(order_to_send_id)
            if state.get("status") == "error":
                raise ProviderError(f"eColet could not book the courier: {state.get('error') or 'unknown error'}")
            if state.get("status") == "ordered" and state.get("order_id"):
                return int(state["order_id"])
            if time.monotonic() >= deadline:
                raise ProviderError(
                    f"eColet has not booked order-to-send {order_to_send_id} after {self._awb_wait}s; "
                    "it may still go through — check the eColet panel before retrying."
                )
            time.sleep(_POLL_INTERVAL_SECONDS)

    def _locality_id(self, address: Address) -> int | None:
        """eColet's locality id: search by name, prefer the one in the same county."""
        if not address.city:
            return None
        country = address.country or "RO"
        candidates = self.client.search_localities(country, address.city)
        county = (address.region or "").strip().lower()
        city = address.city.strip().lower()
        for loc in candidates:
            if loc.get("name", "").lower() == city and (loc.get("county") or {}).get("name", "").lower() == county:
                return int(loc["id"])
        for loc in candidates:
            if (loc.get("county") or {}).get("name", "").lower() == county:
                return int(loc["id"])
        return int(candidates[0]["id"]) if candidates else None

    def _default_sender(self) -> Address:
        """The account's default address-book entry, when the caller sends no sender."""
        from bapp_connectors.core.dto import Address

        user = self.client.me()
        entries = self.client.address_book()
        entry = next((e for e in entries if e.get("id") == user.get("default_address_id")), entries[0] if entries else None)
        if not entry:
            raise ValidationError("eColet needs a sender address: pass shipment.sender or add one to the address book.")
        return Address(
            street=entry.get("street_name", ""), city=entry.get("locality", ""), region=entry.get("county", ""),
            postal_code=entry.get("postal_code", ""), country=(entry.get("country") or "ro").upper(),
            extra={"name": entry.get("name", ""), "phone": entry.get("phone", ""), "email": entry.get("email", ""),
                   "number": entry.get("street_number", ""), "contact_name": entry.get("contact_person", "")},
        )
