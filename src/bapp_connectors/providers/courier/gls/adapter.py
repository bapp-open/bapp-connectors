"""
GLS courier adapter — implements CourierPort.

This is the main entry point for the GLS integration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import BatchTrackingCapability
from bapp_connectors.core.dto import (
    AWBLabel,
    ConnectionTestResult,
    PaginatedResult,
    Shipment,
    TrackingEvent,
)
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import CourierPort
from bapp_connectors.providers.courier.gls.client import (
    STATUS_BATCH_SIZE,
    GLSApiClient,
    build_base_url,
    unpack_delivery_points,
)
from bapp_connectors.providers.courier.gls.errors import format_gls_errors, raise_for_gls_errors
from bapp_connectors.providers.courier.gls.manifest import manifest
from bapp_connectors.providers.courier.gls.mappers import (
    GLSServiceSettings,
    as_bool,
    awb_label_from_gls,
    build_awb_payload,
    shipments_from_gls,
    tracking_batch_from_gls,
    tracking_events_from_gls,
)

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class GLSCourierAdapter(CourierPort, BatchTrackingCapability):
    """
    GLS courier adapter.

    Implements:
    - CourierPort: AWB generation, tracking, shipment management
    - BatchTrackingCapability: tracking for up to 100 AWBs per request
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        country = (credentials.get("country") or "RO").lower()
        test = str(credentials.get("test", "false")).lower() in ("true", "1", "yes")

        self._client_number = int(credentials.get("client_number") or 0)
        self._printer_type = config.get("printer_type") or "Connect"
        self._services = GLSServiceSettings.from_config(config)

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=build_base_url(country, test),
                auth=NoAuth(),
                provider_name="gls",
            )

        self.client = GLSApiClient(
            http_client=http_client,
            username=credentials.get("username", ""),
            password=credentials.get("password", ""),
            client_number=self._client_number,
            printer_type=self._printer_type,
            country=country,
            test=test,
            hide_phone_on_label=as_bool(config.get("hide_phone_on_label")),
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
        payload = build_awb_payload(shipment, client_number=self._client_number, services=self._services)
        response = self.client.generate_awb(payload)
        label = awb_label_from_gls(response)
        errors = response.get("PrintLabelsErrorList") or []

        if not label.tracking_number:
            raise_for_gls_errors(errors, "PrintLabels")
            raise ValidationError("GLS PrintLabels: no parcel number returned.")
        if errors:
            # the parcel exists at GLS: report the problem, but do not lose the AWB
            logger.warning("GLS PrintLabels for %s returned errors: %s", label.tracking_number, format_gls_errors(errors))

        # Attempt to download labels if we got a parcel ID but no label bytes
        if label.label_pdf is None and label.extra.get("parcel_id"):
            parcel_ids = [p["ParcelId"] for p in label.extra.get("parcels") or [] if p.get("ParcelId")]
            try:
                resp = self.client.get_printed_labels(parcel_ids or [label.extra["parcel_id"]])
                raw_labels = resp.get("Labels")
                if raw_labels:
                    label = label.model_copy(update={"label_pdf": bytes(raw_labels)})
            except ProviderError:
                logger.warning("GLS label download failed for AWB %s", label.tracking_number, exc_info=True)

        return label

    def get_tracking(self, tracking_number: str) -> list[TrackingEvent]:
        response = self.client.get_parcel_status(tracking_number)
        # status pollers walk the AWBs of every tenant one by one: one bad login must not stop the rest
        self._check_tracking_errors(response.get("GetParcelStatusErrors"), "GetParcelStatuses", raise_auth=False)
        return tracking_events_from_gls(response)

    @staticmethod
    def _check_tracking_errors(errors: list | None, operation: str, raise_auth: bool = True) -> None:
        """A per-parcel error (unknown number, not scanned yet) only means "no tracking" and is logged;
        bad credentials are raised when `raise_auth`."""
        errors = errors or []
        if raise_auth and any(isinstance(e, dict) and e.get("ErrorCode") == -1 for e in errors):
            raise_for_gls_errors(errors, operation)
        if errors:
            logger.warning("GLS %s: %s", operation, format_gls_errors(errors))

    def cancel_shipment(self, tracking_number: str) -> bool:
        """
        Cancel a GLS shipment.

        GLS deletes by ParcelId (`AWBLabel.extra["parcel_id"]`), not by the AWB number;
        deleting the first ParcelId of a multi-parcel shipment deletes all its parcels.
        Works only before the parcel is handed over to GLS.
        """
        try:
            parcel_id = int(tracking_number)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"GLS cancels by ParcelId (a number), got {tracking_number!r}.") from exc
        response = self.client.delete_parcel(parcel_id)
        raise_for_gls_errors(response.get("DeleteLabelsErrorList"), "DeleteLabels")
        return bool(response.get("SuccessfullyDeletedList"))

    def get_shipments(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Shipment]:
        response = self.client.get_parcel_list(period_start=since)
        raise_for_gls_errors(response.get("GetParcelListErrors"), "GetParcelList")
        return shipments_from_gls(response)

    # ── BatchTrackingCapability ──

    def get_tracking_batch(self, tracking_numbers: list[str]) -> dict[str, list[TrackingEvent]]:
        numbers = []
        for number in dict.fromkeys(str(n).strip() for n in tracking_numbers):
            if number.isdigit():
                numbers.append(int(number))
            elif number:
                logger.warning("GLS tracking: %r is not a parcel number, skipped", number)
        result: dict[str, list[TrackingEvent]] = {}
        for start in range(0, len(numbers), STATUS_BATCH_SIZE):
            response = self.client.get_parcel_list_statuses(numbers[start:start + STATUS_BATCH_SIZE])
            self._check_tracking_errors(response.get("GetParcelListStatusesErrors"), "GetParcelListStatuses")
            result.update(tracking_batch_from_gls(response))
        return result

    # ── GLS-specific ──

    def get_delivery_points(self, country: str | None = None) -> list[dict]:
        """ParcelShops, ParcelLockers and depots of a country (MasterDataService/GetDeliveryPoints).

        Raw GLS `DeliveryPoint` dicts (Id, Matchcode, Address, Latitude, Longitude,
        DeliveryPointType 1=ParcelShop 2=ParcelLocker 3=Depot, CodHandler, ...). The `Id`
        is what `recipient.extra["pickup_point_id"]` takes. Large: cache it."""
        response = self.client.get_delivery_points(country)
        if response.get("ErrorCode"):
            raise_for_gls_errors([response], "GetDeliveryPoints")
        return unpack_delivery_points(response.get("Data"))
