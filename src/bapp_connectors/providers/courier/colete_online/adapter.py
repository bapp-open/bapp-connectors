"""
Colete Online courier adapter — implements CourierPort.

This is the main entry point for the Colete Online integration.

Colete Online is a courier aggregator — it routes shipments to the best-priced
courier (FAN Courier, Sameday, DPD, Cargus, etc.) based on service selection.
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
from bapp_connectors.providers.courier.colete_online.client import ColeteOnlineApiClient
from bapp_connectors.providers.courier.colete_online.manifest import manifest
from bapp_connectors.providers.courier.colete_online.mappers import (
    awb_label_from_co,
    build_order_payload,
    tracking_events_from_co,
)

if TYPE_CHECKING:
    from datetime import datetime


class ColeteOnlineCourierAdapter(CourierPort):
    """
    Colete Online courier adapter.

    Implements:
    - CourierPort: AWB generation, tracking, shipment management
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._staging = config.get("staging", True)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=NoAuth(),
                provider_name="colete_online",
            )

        self.client = ColeteOnlineApiClient(
            http_client=http_client,
            client_id=credentials.get("client_id", ""),
            client_secret=credentials.get("client_secret", ""),
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
        payload = build_order_payload(shipment)
        response = self.client.create_order(payload, staging=self._staging)
        label = awb_label_from_co(response)

        # Attempt to download the PDF label
        unique_id = label.extra.get("unique_id", "")
        if unique_id:
            try:
                pdf_bytes = self.client.download_awb(unique_id, staging=self._staging)
                if pdf_bytes:
                    label = label.model_copy(update={"label_pdf": pdf_bytes})
            except Exception:
                pass  # PDF download is best-effort

        return label

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        response = self.client.get_order_status(tracking_number, staging=self._staging)
        return tracking_events_from_co(response)

    def cancel_shipment(self, tracking_number: str) -> bool:
        # Colete Online does not expose a delete/cancel endpoint in the Postman collection.
        # The tracking_number here is the uniqueId from order creation.
        # Cancel may need to be done through the underlying courier directly.
        raise NotImplementedError(
            "Colete Online does not expose a cancel/delete endpoint. "
            "Cancellation should be done through the Colete Online dashboard or the underlying courier."
        )

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        # Colete Online does not expose an order listing endpoint in the API.
        # Return empty result.
        return PaginatedResult(items=[], cursor=None, has_more=False, total=0)
