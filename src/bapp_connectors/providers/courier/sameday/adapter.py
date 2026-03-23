"""
Sameday courier adapter — implements CourierPort.

This is the main entry point for the Sameday integration.
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
from bapp_connectors.providers.courier.sameday.client import SamedayApiClient
from bapp_connectors.providers.courier.sameday.manifest import manifest
from bapp_connectors.providers.courier.sameday.mappers import (
    awb_label_from_sameday,
    build_awb_payload,
    shipments_from_sameday,
    tracking_events_from_sameday,
)

if TYPE_CHECKING:
    from datetime import datetime


class SamedayCourierAdapter(CourierPort):
    """
    Sameday courier adapter.

    Implements:
    - CourierPort: AWB generation, tracking, shipment management
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self._pickup_point_id: int | None = config.get("pickup_point_id")
        self._service_id: int = config.get("service_id", 7)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=NoAuth(),
                provider_name="sameday",
            )

        self.client = SamedayApiClient(
            http_client=http_client,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
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
        pickup_point_id = self._resolve_pickup_point(shipment)
        service_id = shipment.extra.get("service_id", self._service_id) if shipment.extra else self._service_id
        payload = build_awb_payload(shipment, pickup_point_id=pickup_point_id, service_id=service_id)
        response = self.client.generate_awb(payload)
        label = awb_label_from_sameday(response)

        # Attempt to download the PDF label
        if label.tracking_number:
            try:
                pdf_bytes = self.client.download_awb(label.tracking_number)
                if pdf_bytes:
                    label = label.model_copy(update={"label_pdf": pdf_bytes})
            except Exception:
                pass  # PDF download is best-effort

        return label

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        response = self.client.get_parcel_status(tracking_number)
        return tracking_events_from_sameday(response)

    def cancel_shipment(self, tracking_number: str) -> bool:
        try:
            return self.client.delete_parcel(tracking_number)
        except Exception:
            return False

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        page = int(cursor) if cursor else 1
        response = self.client.get_awb_list(page=page)
        return shipments_from_sameday(response)

    # ── Helpers ──

    def _resolve_pickup_point(self, shipment: Shipment) -> int:
        """Resolve the pickup point ID from shipment extras, adapter config, or fetch the default."""
        if shipment.extra and "pickup_point_id" in shipment.extra:
            return int(shipment.extra["pickup_point_id"])
        if self._pickup_point_id is not None:
            return self._pickup_point_id

        # Fall back to the default pickup point from the API
        points = self.client.get_pickup_points()
        for point in points:
            if isinstance(point, dict) and point.get("defaultPickupPoint"):
                self._pickup_point_id = point["id"]
                return self._pickup_point_id

        # If no default, use the first one
        if points and isinstance(points[0], dict):
            self._pickup_point_id = points[0].get("id", 0)
            return self._pickup_point_id

        raise ValueError("No pickup point available. Provide pickup_point_id in adapter config or shipment extras.")
