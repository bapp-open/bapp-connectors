"""
DPD Romania API client. Every operation is a POST with the credentials in the body;
business and auth errors come back as HTTP 200 with an `error` object, so the body is
checked, not the status. Absolute URLs: the registry injects a NoAuth client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

_AUTH_MESSAGES = ("authenticate", "autentificare", "username format")


class DpdApiError(ProviderError):
    """DPD answered with an `error` object; `context` is its machine key."""

    def __init__(self, message: str, *, code=None, context: str = "", component: str = ""):
        super().__init__(message)
        self.code = code
        self.context = context
        self.component = component


class DpdApiClient:
    def __init__(self, http_client: ResilientHttpClient, base_url: str, username: str, password: str):
        self.http = http_client
        self.base_url = base_url.rstrip("/") + "/"
        self._auth = {"userName": username, "password": password, "language": "EN"}

    def _call(self, path: str, body: dict | None = None, *, raw: bool = False, **kwargs) -> Any:
        try:
            response = self.http.call(
                "POST", self.base_url + path, json={**self._auth, **(body or {})},
                headers={"Accept": "application/json"}, direct_response=True, **kwargs,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"DPD {path} failed: {exc}") from exc
        is_json = "json" in (response.headers.get("Content-Type") or "")
        if raw and response.status_code < 400 and not is_json:
            return response.content
        try:
            data = response.json()
        except ValueError:
            raise ProviderError(f"DPD {path}: HTTP {response.status_code} {response.text[:200]}",
                                status_code=response.status_code) from None
        if isinstance(data, dict) and data.get("error"):
            _raise(data["error"], path)
        if response.status_code >= 400:
            raise ProviderError(f"DPD {path}: HTTP {response.status_code}", status_code=response.status_code)
        return data

    # ── Account / nomenclators ──

    def own_client_id(self) -> int:
        return int(self._call("client").get("clientId"))

    def contract_clients(self) -> list[dict]:
        return self._call("client/contract").get("clients") or []

    def find_sites(self, country_id: int, name: str = "", region: str = "", post_code: str = "") -> list[dict]:
        body: dict = {"countryId": country_id}
        if name:
            body["name"] = name
        if region:
            body["region"] = region
        if post_code:
            body["postCode"] = post_code
        return self._call("location/site", body).get("sites") or []

    def find_streets(self, site_id: int, name: str) -> list[dict]:
        return self._call("location/street", {"siteId": site_id, "name": name}).get("streets") or []

    # ── Shipments ──

    def create_shipment(self, body: dict) -> dict:
        """Never retried: a retry after a timeout could create a second shipment."""
        return self._call("shipment", body, retry=False, log_body=True)

    def print_labels(self, parcel_ids: list[str], paper_size: str = "A6") -> bytes:
        body = {"paperSize": paper_size, "format": "pdf", "parcels": [{"parcel": {"id": pid}} for pid in parcel_ids]}
        return self._call("print", body, raw=True)

    def track(self, parcel_ids: list[str]) -> list[dict]:
        return self._call("track", {"parcels": [{"id": pid} for pid in parcel_ids[:10]]}).get("parcels") or []

    def cancel_shipment(self, shipment_id: str, comment: str = "Anulat din BAPP") -> dict:
        return self._call("shipment/cancel", {"shipmentId": shipment_id, "comment": comment}, retry=False,
                          log_body=True)


def _raise(error: dict, path: str):
    message = str(error.get("message") or "unknown error")
    if error.get("code") == 1 and any(m in message.lower() for m in _AUTH_MESSAGES):
        raise AuthenticationError(f"DPD: {message}")
    raise DpdApiError(f"DPD {path}: {message}", code=error.get("code"), context=error.get("context") or "",
                      component=error.get("component") or "")
