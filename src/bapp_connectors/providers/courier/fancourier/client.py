"""
FAN Courier API v2 client — HTTP calls and the token only; mapping lives in mappers.py.

Every call uses an absolute URL and its own Authorization header: the registry
injects a client built from the manifest with NoAuth. Array parameters are the
literal `awb[]=` / `awbs[]=` repeated, so they go as a list of tuples.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

_TOKEN_MARGIN_SECONDS = 600
_BUCHAREST = ZoneInfo("Europe/Bucharest")  # expiresAt carries no timezone


class FanCourierApiClient:
    def __init__(self, http_client: ResilientHttpClient, base_url: str, username: str, password: str):
        self.http = http_client
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self._token = ""
        self._expires_at = 0.0

    # ── Auth ──

    def _login(self) -> str:
        try:
            response = self.http.call(
                "POST", self.base_url + "login", params={"username": self.username, "password": self.password},
                headers={"Accept": "application/json"}, direct_response=True, retry=False,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"FAN Courier login failed: {exc}") from exc
        body = _json(response)
        token = (body.get("data") or {}).get("token") if isinstance(body.get("data"), dict) else None
        if body.get("status") != "success" or not token:
            raise AuthenticationError(f"FAN Courier login failed: {body.get('message') or response.status_code}")
        self._token = token
        self._expires_at = _expiry(body["data"].get("expiresAt"))
        return token

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._expires_at:
            return self._token
        return self._login()

    def _call(self, method: str, path: str, *, raw: bool = False, **kwargs) -> Any:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._ensure_token()}", "Accept": "application/json"}
            try:
                response = self.http.call(method, self.base_url + path, headers=headers, direct_response=True, **kwargs)
            except requests.RequestException as exc:
                raise ProviderError(f"FAN Courier {method} {path} failed: {exc}") from exc
            if response.status_code == 401 and attempt == 1:
                self._token = ""  # expired before expiresAt: log in again once
                continue
            break
        if response.status_code == 401:
            raise AuthenticationError("FAN Courier rejected the token (401).")
        if raw and response.status_code < 400 and not _is_json(response):
            return response
        body = _json(response)
        if response.status_code >= 400 or body.get("status") in ("fail", "error"):
            raise ProviderError(f"FAN Courier {path}: {_error_text(body) or response.status_code}",
                                status_code=response.status_code)
        return body

    # ── Nomenclators ──

    def branches(self) -> list[dict]:
        return self._call("GET", "reports/branches").get("data") or []

    def services(self) -> list[dict]:
        return self._call("GET", "reports/services").get("data") or []

    # ── AWB ──

    def create_awb(self, body: dict) -> list[dict]:
        """POST /intern-awb; per-shipment results in `response`, never retried (would book twice)."""
        result = self._call("POST", "intern-awb", json=body, retry=False, log_body=True)
        if "response" not in result:
            raise ProviderError(f"FAN Courier intern-awb: {_error_text(result) or 'no response'}")
        return result["response"] or []

    def label(self, client_id: str, awb: str, fmt: str = "A4") -> bytes:
        params = [("clientId", client_id), ("awbs[]", awb), ("pdf", 1), ("format", fmt)]
        response = self._call("GET", "awb/label", raw=True, params=params)
        if isinstance(response, dict):  # JSON body = error, already raised unless status was odd
            raise ProviderError(f"FAN Courier label: {_error_text(response)}")
        return response.content

    def tracking(self, client_id: str, awbs: list[str]) -> list[dict]:
        params = [("clientId", client_id), *[("awb[]", a) for a in awbs], ("language", "ro")]
        return self._call("GET", "reports/awb/tracking", params=params).get("data") or []

    def delete_awb(self, client_id: str, awb: str) -> dict:
        return self._call("DELETE", "awb", params={"clientId": client_id, "awb": awb}, retry=False, log_body=True)

    def awb_report(self, client_id: str, date: str, page: int = 1, per_page: int = 100) -> dict:
        """The shipping slip of one day (no date ranges in the API)."""
        return self._call("GET", "reports/awb", params={"clientId": client_id, "date": date, "page": page,
                                                         "perPage": per_page})


def _expiry(value) -> float:
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BUCHAREST)
        return dt.timestamp() - _TOKEN_MARGIN_SECONDS
    except (TypeError, ValueError):
        return time.time() + 23 * 3600  # documented lifetime is 24h


def _is_json(response) -> bool:
    return "json" in (response.headers.get("Content-Type") or "")


def _json(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"data": body}


def _error_text(body: dict) -> str:
    errors = body.get("errors")
    if isinstance(errors, dict):
        return "; ".join(f"{k}: {v}" for k, v in errors.items())
    if isinstance(errors, list):
        return "; ".join(map(str, errors))
    return str(body.get("message") or "")
