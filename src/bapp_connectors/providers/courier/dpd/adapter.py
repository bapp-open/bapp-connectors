"""
DPD Romania adapter — implements CourierPort.

Creating a shipment does not order a pickup (that is POST /pickup, not implemented):
accounts with a standing daily pickup need nothing more.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import AWBLabel, ConnectionTestResult, PaginatedResult, Shipment, TrackingEvent
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.dpd.client import DpdApiClient, DpdApiError
from bapp_connectors.providers.courier.dpd.manifest import DPD_API_URL, ROMANIA_ID, manifest
from bapp_connectors.providers.courier.dpd.mappers import (
    awb_label_from_dpd,
    build_recipient,
    build_shipment_body,
    plain,
    split_street,
    tracking_events_from_dpd,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import Address

logger = logging.getLogger(__name__)


class DpdCourierAdapter(CourierPort):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._client_id = str(credentials.get("client_id") or "").strip()
        self._service_id = int(config.get("service_id") or 2505)
        self._payer = config.get("payer") or "SENDER"
        self._paper_size = config.get("paper_size") or "A6"
        self._package = config.get("package") or "BOX"
        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="dpd")
        self.client = DpdApiClient(http_client=http_client, base_url=DPD_API_URL,
                                   username=credentials.get("username", ""), password=credentials.get("password", ""))

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            client_id = self.client.own_client_id()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        return ConnectionTestResult(success=True, message=f"Connected; client {client_id}")

    # ── CourierPort ──

    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        recipient = shipment.recipient
        if not recipient:
            raise ValidationError("DPD needs the recipient address.")
        site_id = street_id = None
        street_name, street_no = split_street(recipient.street, (recipient.extra or {}).get("number") or "")
        if not (recipient.extra or {}).get("pickup_point_id"):
            site_id = self._site_id(recipient)
            if site_id and street_name:
                street_id = self._street_id(site_id, street_name)
        body = build_shipment_body(shipment, build_recipient(recipient, site_id, street_id, street_no),
                                   self._client_id, self._service_id, self._payer, self._package)
        try:
            response = self.client.create_shipment(body)
        except DpdApiError as exc:
            raise ValidationError(str(exc)) from exc
        label = awb_label_from_dpd(response, None)
        if not label.tracking_number:
            raise ProviderError("DPD returned no shipment id.")
        try:
            pdf = self.client.print_labels(label.extra["parcel_ids"] or [label.tracking_number], self._paper_size)
            if isinstance(pdf, bytes) and pdf[:4] == b"%PDF":
                label = label.model_copy(update={"label_pdf": pdf})
        except ProviderError:
            logger.warning("DPD label print failed for shipment %s", label.tracking_number, exc_info=True)
        return label

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        parcels = self.client.track([tracking_number])
        parcel = next((p for p in parcels if str(p.get("parcelId")) == str(tracking_number)), parcels[0] if parcels else None)
        if not parcel or parcel.get("error"):
            return []
        return tracking_events_from_dpd(parcel)

    def cancel_shipment(self, tracking_number: str) -> bool:
        try:
            self.client.cancel_shipment(tracking_number)
        except ProviderError:
            logger.warning("DPD cancel failed for shipment %s", tracking_number, exc_info=True)
            return False
        return True

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        # DPD has no listing by date (only /shipment/search by ref); shipments are tracked by id.
        return PaginatedResult(items=[], cursor=None, has_more=False, total=0)

    # ── Nomenclators ──

    def _site_id(self, address: Address) -> int | None:
        """DPD site: by postcode first (unique for a site), then by name within the county."""
        country = ROMANIA_ID
        if address.postal_code:
            sites = self.client.find_sites(country, post_code=str(address.postal_code))
            if len(sites) == 1:
                return int(sites[0]["id"])
            city = plain(address.city).lower()
            for site in sites:
                if plain(site.get("name")).lower() == city:
                    return int(site["id"])
        if address.city:
            sites = self.client.find_sites(country, name=plain(address.city), region=plain(address.region))
            city = plain(address.city).lower()
            exact = [s for s in sites if plain(s.get("name")).lower() == city]
            if len(exact) == 1 or (exact and not address.region):
                return int(exact[0]["id"])
            if len(sites) == 1:
                return int(sites[0]["id"])
        return None

    def _street_id(self, site_id: int, name: str) -> int | None:
        streets = self.client.find_streets(site_id, name)
        wanted = name.lower()
        exact = [s for s in streets if plain(s.get("name")).lower() == wanted]
        pick = exact[0] if exact else (streets[0] if len(streets) == 1 else None)
        return int(pick["id"]) if pick else None
