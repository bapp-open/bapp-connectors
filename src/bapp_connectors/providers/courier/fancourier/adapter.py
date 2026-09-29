"""
FAN Courier adapter — implements CourierPort on API v2.

Generating an AWB does not order a pickup: FAN collects parcels on the account's
regular pickup, or through a separate courier order (not implemented here).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from bapp_connectors.core.dto import AWBLabel, ConnectionTestResult, PaginatedResult, Shipment, TrackingEvent
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.fancourier.client import FanCourierApiClient
from bapp_connectors.providers.courier.fancourier.manifest import FAN_API_URL, manifest
from bapp_connectors.providers.courier.fancourier.mappers import (
    awb_label_from_fan,
    build_awb_body,
    resolve_service,
    result_errors,
    shipment_from_fan,
    tracking_events_from_fan,
)

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class FanCourierAdapter(CourierPort):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._client_id = str(credentials.get("client_id") or "").strip()
        self._service = (config.get("service") or "Standard").strip()
        self._cod_to_bank = config.get("cod_to_bank_account", True) not in (False, "false", "0", 0)
        self._payer = config.get("payer") or "sender"
        self._label_format = config.get("label_format") or "A4"
        if http_client is None:
            http_client = ResilientHttpClient(base_url=manifest.base_url, auth=NoAuth(), provider_name="fancourier")
        self.client = FanCourierApiClient(
            http_client=http_client,
            base_url=FAN_API_URL,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            branches = self.client.branches()
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))
        ids = [str(b.get("id")) for b in branches]
        if self._client_id and self._client_id not in ids:
            return ConnectionTestResult(success=False, message=f"Client ID {self._client_id} is not a branch of this account ({', '.join(ids)}).")
        return ConnectionTestResult(success=True, message=f"Connected; branches: {', '.join(ids) or '-'}")

    # ── CourierPort ──

    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        if not shipment.recipient:
            raise ValidationError("FAN Courier needs the recipient address.")
        extra = shipment.extra or {}
        service = resolve_service(extra.get("service") or self._service, float(extra.get("cod_amount") or 0),
                                  self._cod_to_bank)
        client_id = self._resolve_client_id()
        results = self.client.create_awb(build_awb_body(shipment, client_id, service, self._payer))
        result = results[0] if results else {}
        if not result.get("awbNumber"):
            raise ValidationError(f"FAN Courier refused the AWB: {result_errors(result) or 'no AWB number returned'}")
        awb = str(result["awbNumber"])
        pdf = None
        try:
            content = self.client.label(client_id, awb, self._label_format)
            pdf = content if content[:4] == b"%PDF" else None
        except ProviderError:
            logger.warning("FAN Courier label download failed for AWB %s", awb, exc_info=True)
        label = awb_label_from_fan(result, pdf)
        return label.model_copy(update={"extra": {**label.extra, "service": service, "client_id": client_id}})

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        entries = self.client.tracking(self._resolve_client_id(), [tracking_number])
        entry = next((e for e in entries if str(e.get("awbNumber")) == str(tracking_number)), None)
        return tracking_events_from_fan(entry) if entry else []

    def cancel_shipment(self, tracking_number: str) -> bool:
        try:
            self.client.delete_awb(self._resolve_client_id(), tracking_number)
        except ProviderError:
            logger.warning("FAN Courier delete failed for AWB %s", tracking_number, exc_info=True)
            return False
        return True

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        """The API lists one day at a time; the cursor walks day by day ("YYYY-MM-DD:page")."""
        today = date.today()
        if cursor:
            day_str, page_str = cursor.split(":")
            day, page = date.fromisoformat(day_str), int(page_str)
        else:
            day, page = (since.date() if since else today), 1
        response = self.client.awb_report(self._resolve_client_id(), day.isoformat(), page=page)
        items = [shipment_from_fan(i) for i in response.get("data") or []]
        per_page = int(response.get("perPage") or 100)
        total = int(response.get("total") or 0)
        if page * per_page < total:
            next_cursor = f"{day.isoformat()}:{page + 1}"
        elif day < today:
            next_cursor = f"{(day + timedelta(days=1)).isoformat()}:1"
        else:
            next_cursor = None
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    # ── Helpers ──

    def _resolve_client_id(self) -> str:
        if not self._client_id:
            branches = self.client.branches()
            if not branches:
                raise ValidationError("FAN Courier account has no branch (clientId); set Client ID on the connection.")
            self._client_id = str(branches[0]["id"])
        return self._client_id
