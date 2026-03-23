"""
GLS API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with NoAuth and manages its own auth payload
(username + SHA-512 hashed password included in every request body).
"""

from __future__ import annotations

import datetime
import hashlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Country-specific base URL template
_BASE_URL_TEMPLATE = "https://api.mygls.{country}/ParcelService.svc/json/"

SUPPORTED_COUNTRIES = ("ro", "hu", "hr", "cz", "si", "sk", "rs")


def build_base_url(country: str) -> str:
    """Build the GLS base URL for a given country code."""
    code = country.lower()
    if code not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported GLS country: {country!r}. Must be one of {SUPPORTED_COUNTRIES}")
    return _BASE_URL_TEMPLATE.format(country=code)


class GLSApiClient:
    """
    Low-level GLS API client.

    This class only handles HTTP calls, auth payload construction, and response parsing.
    Data normalization happens in the adapter via mappers.

    GLS uses a JSON-RPC style API where authentication credentials (username + hashed password)
    are included in every request body.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        username: str,
        password: str,
        client_number: int,
        printer_type: str = "Connect",
    ):
        self.http = http_client
        self._username = username
        self._password_hash = self._hash_password(password)
        self._client_number = client_number
        self._printer_type = printer_type

    @staticmethod
    def _hash_password(plaintext: str) -> list[int]:
        """Hash password with SHA-512 and return as list of byte values (GLS API format)."""
        return list(hashlib.sha512(plaintext.encode()).digest())

    def _auth_payload(self) -> dict[str, Any]:
        """Base payload with authentication credentials, included in every request."""
        return {"Username": self._username, "Password": self._password_hash}

    @staticmethod
    def _date_to_api(date: datetime.date) -> str:
        """Convert a date to GLS API format: /Date(timestamp)/"""
        ts = int(date.strftime("%s")) * 1000
        return f"/Date({ts})/"

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by attempting to list parcels and checking for auth errors."""
        try:
            response = self._get_parcel_list_raw()
            errors = response.get("GetParcelListErrors", [])
            for error in errors:
                if error.get("ErrorCode") == -1:
                    return False
            return True
        except Exception:
            return False

    # ── AWB ──

    def generate_awb(self, parcel_data: dict[str, Any]) -> dict:
        """POST PrintLabels — generate AWB labels for parcels."""
        payload = self._auth_payload()
        payload["TypeOfPrinter"] = self._printer_type
        payload["ParcelList"] = [parcel_data]
        return self.http.call("POST", "PrintLabels", json=payload)

    def delete_parcel(self, parcel_id: int) -> dict:
        """POST DeleteLabels — delete a parcel by its ID (not AWB number)."""
        payload = self._auth_payload()
        payload["ParcelIdList"] = [parcel_id]
        return self.http.call("POST", "DeleteLabels", json=payload)

    # ── Tracking ──

    def get_parcel_status(self, parcel_number: str, language: str = "RO") -> dict:
        """POST GetParcelStatuses — get tracking history for a parcel."""
        payload = self._auth_payload()
        payload["ParcelNumber"] = parcel_number
        payload["LanguageIsoCode"] = language
        payload["ReturnPOD"] = False
        return self.http.call("POST", "GetParcelStatuses", json=payload)

    # ── Parcel List ──

    def get_parcel_list(
        self,
        period_start: datetime.datetime | None = None,
        period_stop: datetime.datetime | None = None,
    ) -> dict:
        """POST GetParcelList — list parcels within a date range."""
        return self._get_parcel_list_raw(period_start, period_stop)

    def _get_parcel_list_raw(
        self,
        period_start: datetime.datetime | None = None,
        period_stop: datetime.datetime | None = None,
    ) -> dict:
        """Internal: raw GetParcelList call."""
        payload = self._auth_payload()
        if period_start is None:
            period_start = datetime.datetime.now() - datetime.timedelta(hours=8)
        if period_stop is None:
            period_stop = datetime.datetime.now()
        payload["PrintDateFrom"] = self._date_to_api(period_start)
        payload["PrintDateTo"] = self._date_to_api(period_stop)
        return self.http.call("POST", "GetParcelList", json=payload)

    # ── Label download ──

    def get_printed_labels(self, parcel_ids: list[int]) -> dict:
        """POST GetPrintedLabels — download labels for already generated parcels."""
        payload = self._auth_payload()
        payload["ParcelIdList"] = parcel_ids
        payload["TypeOfPrinter"] = self._printer_type
        return self.http.call("POST", "GetPrintedLabels", json=payload)
