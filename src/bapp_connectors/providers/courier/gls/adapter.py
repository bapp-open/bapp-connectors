"""
GLS courier adapter — implements CourierPort.

This is the main entry point for the GLS integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    AWBLabel,
    ConnectionTestResult,
    PaginatedResult,
    Shipment,
    TrackingEvent,
)
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.gls.client import GLSApiClient, build_base_url
from bapp_connectors.providers.courier.gls.manifest import manifest
from bapp_connectors.providers.courier.gls.mappers import (
    awb_label_from_gls,
    build_awb_payload,
    shipments_from_gls,
    tracking_events_from_gls,
)

if TYPE_CHECKING:
    from datetime import datetime


class GLSCourierAdapter(CourierPort):
    """
    GLS courier adapter.

    Implements:
    - CourierPort: AWB generation, tracking, shipment management
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        country = credentials.get("country", "RO").lower()
        base_url = build_base_url(country)

        self._client_number = int(credentials.get("client_number", 0))
        self._printer_type = config.get("printer_type", "Connect")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=base_url,
                auth=NoAuth(),
                provider_name="gls",
            )

        self.client = GLSApiClient(
            http_client=http_client,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            client_number=self._client_number,
            printer_type=self._printer_type,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            success = self.client.test_auth()
            return ConnectionTestResult(
                success=success,
                message="Connection successful" if success else "Authentication failed",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── CourierPort ──

    def generate_awb(self, shipment: Shipment) -> AWBLabel:
        payload = build_awb_payload(shipment, client_number=self._client_number)
        response = self.client.generate_awb(payload)
        label = awb_label_from_gls(response)

        # Attempt to download labels if we got a parcel ID but no label bytes
        if label.label_pdf is None and label.extra.get("parcel_id"):
            try:
                resp = self.client.get_printed_labels([label.extra["parcel_id"]])
                raw_labels = resp.get("Labels")
                if raw_labels:
                    label = label.model_copy(update={"label_pdf": bytes(raw_labels)})
            except Exception:
                pass  # Label download is best-effort

        return label

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        response = self.client.get_parcel_status(tracking_number)
        return tracking_events_from_gls(response)

    def cancel_shipment(self, tracking_number: str) -> bool:
        """
        Cancel a GLS shipment.

        Note: GLS uses ParcelId (not AWB number) for deletion. The tracking_number
        should be the ParcelId. If it's the AWB number, this may not work — the caller
        should pass the parcel_id from the AWB generation response extras.
        """
        try:
            response = self.client.delete_parcel(int(tracking_number))
            return bool(response.get("SuccessfullyDeletedList"))
        except (ValueError, Exception):
            return False

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        response = self.client.get_parcel_list(period_start=since)
        return shipments_from_gls(response)
