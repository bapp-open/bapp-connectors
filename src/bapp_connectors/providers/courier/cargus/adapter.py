"""
Cargus adapter — implements CourierPort.

AWBs gather in an open pickup order per LocationId, which Cargus closes at the point's
AutomaticEOD (or through PUT Orders, not implemented here).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from bapp_connectors.core.dto import AWBLabel, ConnectionTestResult, PaginatedResult, Shipment, TrackingEvent
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.cargus.client import CargusApiClient, CargusApiError
from bapp_connectors.providers.courier.cargus.manifest import CARGUS_LIVE_URL, CARGUS_TEST_URL, manifest
from bapp_connectors.providers.courier.cargus.mappers import (
    awb_label_from_cargus,
    build_awb_body,
    shipment_from_cargus,
    tracking_events_from_cargus,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class CargusCourierAdapter(CourierPort):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        location = str(credentials.get("pickup_location_id") or "").strip()
        self._location_id = int(location) if location.isdigit() else None
        self._service_id = int(config.get("service_id") or 34)
        self._cod_to_bank = config.get("cod_to_bank_account", True) not in (False, "false", "0", 0)
        self._payer = 2 if config.get("payer") == "recipient" else 1
        self._label_format = 1 if config.get("label_format") == "label" else 0
        test = str(credentials.get("test", "false")).lower() in ("true", "1", "yes")
        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="cargus")
        self.client = CargusApiClient(
            http_client=http_client,
            base_url=CARGUS_TEST_URL if test else CARGUS_LIVE_URL,
            subscription_key=credentials.get("subscription_key", ""),
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            points = self.client.pickup_locations()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        ids = [str(p.get("LocationId")) for p in points]
        if self._location_id and str(self._location_id) not in ids:
            return ConnectionTestResult(success=False,
                                        message=f"Pickup location {self._location_id} is not active for this user ({', '.join(ids)}).")
        return ConnectionTestResult(success=True, message=f"Connected; pickup points: {', '.join(ids) or '-'}")

    # ── CourierPort ──

    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        if not shipment.recipient:
            raise ValidationError("Cargus needs the recipient address.")
        body = build_awb_body(shipment, self._resolve_location_id(), self._service_id, self._payer, self._cod_to_bank)
        try:
            awb = self.client.create_awb(body)
        except CargusApiError as exc:
            if exc.status_code and exc.status_code < 500:  # a refusal of the data, not an outage
                raise ValidationError(str(exc)) from exc
            raise
        barcode = str(awb.get("BarCode") or "")
        if not barcode:
            raise ProviderError("Cargus returned no AWB barcode.")
        pdf = None
        try:
            content = self.client.awb_documents([barcode], self._label_format)
            pdf = content if content[:4] == b"%PDF" else None
        except ProviderError:
            logger.warning("Cargus label download failed for AWB %s", barcode, exc_info=True)
        return awb_label_from_cargus(awb, pdf)

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        traces = self.client.trace([tracking_number])
        trace = next((t for t in traces if str(t.get("Code")) == str(tracking_number)), traces[0] if traces else None)
        return tracking_events_from_cargus(trace) if trace else []

    def cancel_shipment(self, tracking_number: str) -> bool:
        try:
            return self.client.delete_awb(tracking_number)
        except ProviderError:
            logger.warning("Cargus delete failed for AWB %s", tracking_number, exc_info=True)
            return False

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        page = int(cursor) if cursor else 1
        start = since or (datetime.now(UTC) - timedelta(days=7))
        items = self.client.awbs_by_date(start.strftime("%m-%d-%Y"), datetime.now(UTC).strftime("%m-%d-%Y"),
                                         page=page, per_page=_PAGE_SIZE)
        has_more = len(items) >= _PAGE_SIZE
        return PaginatedResult(items=[shipment_from_cargus(a) for a in items],
                               cursor=str(page + 1) if has_more else None, has_more=has_more)

    # ── Helpers ──

    def _resolve_location_id(self) -> int:
        if self._location_id is None:
            points = self.client.pickup_locations()
            if not points:
                raise ValidationError("Cargus user has no active pickup point; set Pickup location ID on the connection.")
            self._location_id = int(points[0]["LocationId"])
        return self._location_id
