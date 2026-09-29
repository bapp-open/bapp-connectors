"""
Cargus UrgentOnline API client — subscription key on every call, plus a 24h bearer
token from LoginUser. Absolute URLs: the registry injects a NoAuth client.

Errors come in three shapes: a JSON array of messages, {"Error": "..."} / {"message"},
or a bare JSON string ("Failed to authenticate!").
"""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

_TOKEN_LIFETIME = 23 * 3600  # documented 24h
_AUTH_FAILED = "failed to authenticate"


class CargusApiError(ProviderError):
    """Cargus refused the request; the message is what it said."""


class CargusApiClient:
    def __init__(self, http_client: ResilientHttpClient, base_url: str, subscription_key: str,
                 username: str, password: str):
        self.http = http_client
        self.base_url = base_url.rstrip("/") + "/"
        self.subscription_key = subscription_key
        self.username = username
        self.password = password
        self._token = ""
        self._expires_at = 0.0

    # ── Auth ──

    def _headers(self, with_token: bool = True) -> dict:
        headers = {"Ocp-Apim-Subscription-Key": self.subscription_key, "Accept": "application/json"}
        if with_token:
            headers["Authorization"] = f"Bearer {self._ensure_token()}"
        return headers

    def _login(self) -> str:
        try:
            response = self.http.call("POST", self.base_url + "LoginUser",
                                      json={"UserName": self.username, "Password": self.password},
                                      headers=self._headers(with_token=False), direct_response=True, retry=False)
        except requests.RequestException as exc:
            raise ProviderError(f"Cargus login failed: {exc}") from exc
        body = _json(response)
        if response.status_code != 200 or not isinstance(body, str) or not body or _AUTH_FAILED in body.lower():
            raise AuthenticationError(f"Cargus login failed: {_error_text(body) or response.status_code}")
        self._token = body
        self._expires_at = time.monotonic() + _TOKEN_LIFETIME
        return body

    def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        return self._login()

    def _call(self, method: str, path: str, **kwargs) -> Any:
        for attempt in (1, 2):
            try:
                response = self.http.call(method, self.base_url + path, headers=self._headers(),
                                          direct_response=True, **kwargs)
            except requests.RequestException as exc:
                raise ProviderError(f"Cargus {method} {path} failed: {exc}") from exc
            body = _json(response)
            expired = response.status_code == 401 or (isinstance(body, str) and _AUTH_FAILED in body.lower())
            if expired and attempt == 1:
                self._token = ""  # log in again once, like the official plugin
                continue
            break
        if expired:
            raise AuthenticationError(f"Cargus: {_error_text(body) or 'not authenticated'}")
        if response.status_code == 204:
            return None
        if response.status_code >= 400:
            raise CargusApiError(f"Cargus {path}: {_error_text(body) or response.status_code}",
                                 status_code=response.status_code)
        return body

    # ── Account ──

    def pickup_locations(self) -> list[dict]:
        return self._call("GET", "PickupLocations") or []

    # ── AWB ──

    def create_awb(self, body: dict) -> dict:
        """POST Awbs/WithGetAwb: the created AWB objects. Never retried (a retry could book twice)."""
        result = self._call("POST", "Awbs/WithGetAwb", json=body, retry=False, log_body=True)
        if isinstance(result, list) and result:
            return result[0]
        if isinstance(result, (str, int)):  # plain POST Awbs shape: just the barcode
            return {"BarCode": str(result)}
        raise CargusApiError(f"Cargus Awbs: unexpected answer {str(result)[:200]}")

    def awb_documents(self, barcodes: list[str], label_format: int = 0) -> bytes:
        params = {"barCodes": json.dumps(barcodes), "type": "PDF", "format": label_format, "printMainOnce": 1}
        encoded = self._call("GET", "AwbDocuments", params=params)
        return base64.b64decode(encoded) if isinstance(encoded, str) else b""

    def trace(self, barcodes: list[str]) -> list[dict]:
        return self._call("GET", "AwbTrace", params={"barCode": json.dumps(barcodes)}) or []

    def delete_awb(self, barcode: str) -> bool:
        return self._call("DELETE", "Awbs", params={"barCode": barcode}, retry=False, log_body=True) is True

    def awbs_by_date(self, from_date: str, to_date: str, page: int = 1, per_page: int = 100) -> list[dict]:
        """Dates as MM-dd-yyyy (per the PDF for Awbs/GetByDate)."""
        params = {"FromDate": from_date, "ToDate": to_date, "pageNumber": page, "itemsPerPage": per_page}
        return self._call("GET", "Awbs/GetByDate", params=params) or []


def _json(response):
    try:
        return response.json()
    except ValueError:
        return response.text


def _error_text(body) -> str:
    if isinstance(body, list):
        return "; ".join(map(str, body))
    if isinstance(body, dict):
        return str(body.get("Error") or body.get("message") or body.get("Message") or "")
    return str(body or "")
