"""
eColet API client — HTTP calls and the OAuth token only; mapping lives in mappers.py.

Paths come from the OpenAPI spec (docs/api-docs.json v1.0.3). The injected
ResilientHttpClient keeps its retry policy and rate limiter, but every call uses an
absolute URL and sets its own Authorization header: the registry builds that client
from the manifest's placeholder base_url with NoAuth.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

_TOKEN_MARGIN_SECONDS = 120


class EcoletApiClient:
    def __init__(
        self,
        http_client: ResilientHttpClient,
        base_url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
    ):
        self.http = http_client
        self.base_url = base_url.rstrip("/") + "/"
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0

    # ── Auth ──

    def _token_request(self, data: dict) -> None:
        try:
            response = self.http.call(
                "POST", self.base_url + "v1/oauth/token", data={**data, "client_id": self.client_id,
                                                                  "client_secret": self.client_secret, "scope": ""},
                headers={"Accept": "application/json"}, direct_response=True, retry=False,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"eColet login failed: {exc}") from exc
        body = _json(response)
        if response.status_code != 200 or not body.get("access_token"):
            raise AuthenticationError(f"eColet login failed: {body.get('message') or response.status_code}")
        self._access_token = body["access_token"]
        # the refresh token rotates: keep the newest one
        self._refresh_token = body.get("refresh_token", "")
        self._expires_at = time.monotonic() + int(body.get("expires_in") or 3600) - _TOKEN_MARGIN_SECONDS

    def _ensure_token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at:
            return self._access_token
        if self._refresh_token:
            try:
                self._token_request({"grant_type": "refresh_token", "refresh_token": self._refresh_token})
                return self._access_token
            except AuthenticationError:
                self._refresh_token = ""
        self._token_request({"grant_type": "password", "username": self.username, "password": self.password})
        return self._access_token

    def _call(self, method: str, path: str, *, raw: bool = False, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {self._ensure_token()}", "Accept": "application/json",
                   "Accept-Language": "ro"}
        try:
            response = self.http.call(method, self.base_url + path, headers=headers, direct_response=True, **kwargs)
        except requests.RequestException as exc:
            raise ProviderError(f"eColet {method} {path} failed: {exc}") from exc
        if response.status_code == 401:
            self._access_token = ""
            raise AuthenticationError("eColet rejected the token (401).")
        if raw:
            if response.status_code >= 400:
                raise ProviderError(f"eColet {path}: HTTP {response.status_code}", status_code=response.status_code)
            return response
        body = _json(response)
        if response.status_code >= 400:
            raise ProviderError(f"eColet {path}: {_error_text(body) or response.status_code}",
                                status_code=response.status_code)
        return body

    # ── Account / nomenclators ──

    def me(self) -> dict:
        body = self._call("GET", "v1/me")
        if body.get("unauthenticated"):  # /me answers 200 {"unauthenticated": true} without a valid token
            raise AuthenticationError("eColet: not authenticated.")
        return body.get("user") or {}

    def services(self) -> list[dict]:
        return self._call("GET", "v1/services").get("services") or []

    def address_book(self, page: int = 1) -> list[dict]:
        return self._call("GET", "v1/address-book", params={"page": page}).get("data") or []

    def search_localities(self, country: str, query: str) -> list[dict]:
        return self._call("GET", f"v1/locations/{country.lower()}/localities/{quote(query[:70], safe='')}").get(
            "localities") or []

    # ── Orders ──

    def reload_form(self, body: dict) -> dict:
        """Prices, availability and pickup slots per service slug; errors can come with 200."""
        return self._call("POST", "v2/add-parcel/reload-form", json=body, log_body=True).get("form") or {}

    def send_order(self, body: dict) -> int:
        """Books the shipment asynchronously; returns the order-to-send id, not an AWB."""
        response = self._call("POST", "v2/add-parcel/send-order", json=body, retry=False, log_body=True)
        return int(response["order_to_send_id"])

    def order_to_send(self, order_to_send_id: int) -> dict:
        return self._call("GET", f"v1/order-to-send/{order_to_send_id}").get("order_to_send") or {}

    def order(self, order_id: int) -> dict:
        return self._call("GET", f"v1/order/{order_id}").get("data") or {}

    def download_waybill(self, order_id: int) -> tuple[bytes, str]:
        response = self._call("GET", f"v1/order/{order_id}/download-waybill", raw=True)
        return response.content, response.headers.get("Content-Type", "")

    def statuses_by_awb(self, awbs: list[str]) -> list[dict]:
        return self._call("POST", "v1/order/get-statuses-for-many-orders", json={"awbs": awbs}).get("data") or []

    def cancel_order(self, order_id: int) -> dict:
        return self._call("DELETE", f"v1/order/{order_id}", retry=False, log_body=True)

    def list_orders(self, page: int = 1, date_from: str = "", date_to: str = "") -> dict:
        """Panel endpoint (not in the public spec): Laravel paginator {data, meta}."""
        params: dict = {"page": page}
        if date_from:
            params.update({"dateType": "created", "dateFrom": date_from, "dateTo": date_to or date_from})
        return self._call("GET", "v1/order", params=params)


def _json(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"data": body}


def _error_text(body: dict) -> str:
    """Laravel 422 {message, errors{field:[msg]}} or {general_error}."""
    if body.get("general_error"):
        return str(body["general_error"])
    if isinstance(body.get("errors"), dict):
        return "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in body["errors"].items())
    return str(body.get("message") or body.get("error") or "")
