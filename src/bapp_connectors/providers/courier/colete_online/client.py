"""
Colete Online API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with NoAuth and manages its own OAuth2 token lifecycle.
Auth flow: POST https://auth.colete-online.ro/token with Basic(clientId:clientSecret)
           grant_type=client_credentials -> returns access_token.
All subsequent calls use Bearer token.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

_AUTH_URL = "https://auth.colete-online.ro/token"
_TOKEN_REFRESH_MARGIN = 300  # 5 minutes before expiry


class ColeteOnlineApiClient:
    """
    Low-level Colete Online API client.

    This class only handles HTTP calls, OAuth2 token management, and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        client_id: str,
        client_secret: str,
    ):
        self.http = http_client
        self._client_id = client_id
        self._client_secret = client_secret

        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Token management ──

    def _ensure_token(self) -> str:
        """Authenticate if the current token is missing or expired."""
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token
        return self._authenticate()

    def _authenticate(self) -> str:
        """POST to auth endpoint with client credentials. Returns a fresh token."""
        credentials = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        response = self.http.call(
            "POST",
            _AUTH_URL,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials",
        )

        if isinstance(response, dict):
            token = response.get("access_token", "")
            expires_in = response.get("expires_in", 3600)
        else:
            raise ValueError(f"Unexpected authenticate response: {response!r}")

        if not token:
            raise ValueError("Colete Online authentication returned empty token.")

        self._token = token
        self._token_expires_at = time.monotonic() + max(int(expires_in) - _TOKEN_REFRESH_MARGIN, 60)

        logger.debug("Colete Online token acquired, expires in ~%.0fs", self._token_expires_at - time.monotonic())
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        """Make an authenticated API call, injecting the Bearer token header."""
        token = self._ensure_token()
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by attempting to authenticate."""
        try:
            self._authenticate()
            return True
        except Exception:
            return False

    # ── Orders ──

    def create_order(self, payload: dict[str, Any], staging: bool = True) -> dict:
        """POST /staging/order or /order — create a shipping order."""
        path = "staging/order" if staging else "order"
        return self._call("POST", path, json=payload)

    def get_order_status(self, unique_id: str, staging: bool = True) -> dict:
        """GET /staging/order/status/{uniqueId} — get order status."""
        path = f"staging/order/status/{unique_id}" if staging else f"order/status/{unique_id}"
        return self._call("GET", path)

    def download_awb(self, unique_id: str, format_type: str = "A4", staging: bool = True) -> bytes:
        """GET /staging/order/awb/{uniqueId}?formatType=A4 — download AWB label as PDF."""
        path = f"staging/order/awb/{unique_id}" if staging else f"order/awb/{unique_id}"
        response = self.http.call(
            "GET",
            path,
            headers={"Authorization": f"Bearer {self._ensure_token()}"},
            params={"formatType": format_type},
            direct_response=True,
        )
        return response.content if hasattr(response, "content") else b""

    # ── Price Estimation ──

    def get_price(self, payload: dict[str, Any]) -> dict:
        """POST /order/price — get price estimates for an order."""
        return self._call("POST", "order/price", json=payload)

    # ── Services ──

    def get_services(self) -> list | dict:
        """GET /service/list — list available courier services."""
        return self._call("GET", "service/list")

    # ── Addresses ──

    def get_addresses(self) -> list | dict:
        """GET /address — list saved addresses."""
        return self._call("GET", "address")

    # ── User ──

    def get_balance(self) -> dict:
        """GET /user/balance — get account balance."""
        return self._call("GET", "user/balance")

    # ── Search / Geolocation ──

    def search_location(self, country_code: str, needle: str) -> list | dict:
        """GET /search/location/{countryCode}/{needle} — search for a location."""
        return self._call("GET", f"search/location/{country_code}/{needle}")

    def search_city(self, country_code: str, county: str, needle: str) -> list | dict:
        """GET /search/city/{countryCode}/{county}/{needle} — search for a city."""
        return self._call("GET", f"search/city/{country_code}/{county}/{needle}")

    # ── Shipping Points ──

    def get_shipping_points_localities(self, payload: dict[str, Any]) -> list | dict:
        """POST /shipping-points/localities-list — list localities with shipping points."""
        return self._call("POST", "shipping-points/localities-list", json=payload)

    def get_shipping_points_list(self, county: str, payload: dict[str, Any]) -> list | dict:
        """POST /shipping-points/list/{county} — list shipping points in a county."""
        return self._call("POST", f"shipping-points/list/{county}", json=payload)
