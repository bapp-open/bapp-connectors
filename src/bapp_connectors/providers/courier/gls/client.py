"""
GLS API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with NoAuth and manages its own auth payload
(username + SHA-512 hashed password included in every request body).

Calls use absolute URLs: the registry hands every adapter a client bound to
`manifest.base_url` (the RO host), while GLS has one host per country plus a
`test.` host for each, so the host is chosen here, from the credentials.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

_HOST_TEMPLATE = "https://api.{test}mygls.{country}/"
PARCEL_SERVICE = "ParcelService.svc/json/"
MASTER_DATA_SERVICE = "MasterDataService.svc/json/"

SUPPORTED_COUNTRIES = ("ro", "hu", "hr", "cz", "si", "sk", "rs")

# GetParcelListStatuses takes at most 100 parcel numbers per request
STATUS_BATCH_SIZE = 100

# LanguageIsoCode is ISO 639-1, not the country code (CZ -> CS, SI -> SL)
_STATUS_LANGUAGE = {"ro": "RO", "hu": "HU", "hr": "HR", "cz": "CS", "si": "SL", "sk": "SK", "rs": "EN"}


def build_host(country: str, test: bool = False) -> str:
    """Build the GLS host for a country, production or test (`api.test.mygls.*`)."""
    code = (country or "ro").lower()
    if code not in SUPPORTED_COUNTRIES:
        raise ValueError(f"Unsupported GLS country: {country!r}. Must be one of {SUPPORTED_COUNTRIES}")
    return _HOST_TEMPLATE.format(test="test." if test else "", country=code)


def build_base_url(country: str, test: bool = False) -> str:
    """Build the GLS ParcelService base URL for a given country code."""
    return build_host(country, test) + PARCEL_SERVICE


def status_language(country: str) -> str:
    return _STATUS_LANGUAGE.get((country or "ro").lower(), "EN")


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
        country: str = "ro",
        test: bool = False,
        hide_phone_on_label: bool = False,
    ):
        self.http = http_client
        self.country = (country or "ro").lower()
        self.host = build_host(self.country, test)
        self._username = username
        self._password_hash = self._hash_password(password)
        self._client_number = client_number
        self._printer_type = printer_type
        self._hide_phone_on_label = hide_phone_on_label

    @staticmethod
    def _hash_password(plaintext: str) -> list[int]:
        """Hash password with SHA-512 and return as list of byte values (GLS API format)."""
        return list(hashlib.sha512(plaintext.encode()).digest())

    def _auth_payload(self) -> dict[str, Any]:
        """Base payload with authentication credentials, included in every request."""
        return {"Username": self._username, "Password": self._password_hash}

    def _post(self, method: str, payload: dict, service: str = PARCEL_SERVICE, **kwargs) -> dict:
        return self.http.call("POST", self.host + service + method, json=payload, **kwargs)

    @staticmethod
    def _date_to_api(date: datetime.date) -> str:
        """Convert a date to GLS API format: /Date(milliseconds since epoch)/"""
        if not isinstance(date, datetime.datetime):
            date = datetime.datetime.combine(date, datetime.time())
        return f"/Date({int(date.timestamp() * 1000)})/"

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
        """POST PrintLabels — generate AWB labels for parcels.

        Sent once: a retry after a timeout would create the parcel a second time."""
        payload = self._auth_payload()
        payload["TypeOfPrinter"] = self._printer_type
        payload["WebshopEngine"] = "BAPP"
        if self._hide_phone_on_label:
            payload["HidePhoneNumberOnLabels"] = True
        payload["ParcelList"] = [parcel_data]
        return self._post("PrintLabels", payload, retry=False, log_body=True)

    def delete_parcel(self, parcel_id: int) -> dict:
        """POST DeleteLabels — delete a parcel by its ID (not AWB number)."""
        payload = self._auth_payload()
        payload["ParcelIdList"] = [parcel_id]
        return self._post("DeleteLabels", payload, retry=False, log_body=True)

    # ── Tracking ──

    def get_parcel_status(self, parcel_number: str, language: str | None = None) -> dict:
        """POST GetParcelStatuses — get tracking history for a parcel."""
        payload = self._auth_payload()
        payload["ParcelNumber"] = int(parcel_number)
        payload["LanguageIsoCode"] = language or status_language(self.country)
        payload["ReturnPOD"] = False
        return self._post("GetParcelStatuses", payload)

    def get_parcel_list_statuses(self, parcel_numbers: list[int], language: str | None = None) -> dict:
        """POST GetParcelListStatuses — tracking history for up to 100 parcels at once."""
        if len(parcel_numbers) > STATUS_BATCH_SIZE:
            raise ValueError(f"GetParcelListStatuses accepts at most {STATUS_BATCH_SIZE} parcel numbers")
        payload = self._auth_payload()
        payload["ParcelNumberList"] = parcel_numbers
        payload["LanguageIsoCode"] = language or status_language(self.country)
        return self._post("GetParcelListStatuses", payload)

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
        return self._post("GetParcelList", payload)

    # ── Label download ──

    def get_printed_labels(self, parcel_ids: list[int]) -> dict:
        """POST GetPrintedLabels — download labels for already generated parcels."""
        payload = self._auth_payload()
        payload["ParcelIdList"] = parcel_ids
        payload["TypeOfPrinter"] = self._printer_type
        if self._hide_phone_on_label:
            payload["HidePhoneNumberOnLabels"] = True
        return self._post("GetPrintedLabels", payload)

    # ── Master data ──

    def get_delivery_points(self, country: str | None = None) -> dict:
        """POST MasterDataService/GetDeliveryPoints — ParcelShops, ParcelLockers and depots.

        Raw response; `Data` is GZIP-compressed JSON in a byte array, see `unpack_delivery_points`."""
        payload = self._auth_payload()
        payload["CountryIsoCode"] = (country or self.country).upper()
        return self._post("GetDeliveryPoints", payload, service=MASTER_DATA_SERVICE)


def unpack_delivery_points(data: list[int] | str | bytes | None) -> list[dict]:
    """`GetDeliveryPointsResponse.Data`: a byte array (JSON list of ints, or base64) holding gzip'd JSON."""
    if not data:
        return []
    if isinstance(data, list):
        raw = bytes(data)
    elif isinstance(data, str):
        raw = base64.b64decode(data)
    else:
        raw = data
    return json.loads(gzip.decompress(raw))
