"""
Sameday API client — raw HTTP calls only, no business logic.

Uses ResilientHttpClient with NoAuth and manages its own token lifecycle.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Token is valid for 12 hours, refresh with a margin of 5 minutes.
_TOKEN_EXPIRY_SHORT = 12 * 3600
_TOKEN_REFRESH_MARGIN = 300


class SamedayApiClient:
    """
    Low-level Sameday API client.

    This class only handles HTTP calls, token management, and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        username: str,
        password: str,
        remember_me: bool = False,
    ):
        self.http = http_client
        self._username = username
        self._password = password
        self._remember_me = remember_me

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
        """POST /authenticate with username/password headers. Returns a fresh token."""
        response = self.http.call(
            "POST",
            "authenticate",
            headers={
                "X-Auth-Username": self._username,
                "X-Auth-Password": self._password,
            },
            params={"remember_me": "1"} if self._remember_me else {},
        )
        if isinstance(response, dict):
            token = response.get("token", "")
            expire_at = response.get("expire_at", "")
        else:
            raise ValueError(f"Unexpected authenticate response: {response!r}")

        if not token:
            raise ValueError("Sameday authentication returned empty token.")

        self._token = token
        # Use expire_at from the response if available, otherwise default to 12h.
        if expire_at:
            # expire_at is typically an ISO timestamp; we fall back to the short TTL.
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
                seconds_left = (dt - datetime.now(UTC)).total_seconds()
                self._token_expires_at = time.monotonic() + max(seconds_left - _TOKEN_REFRESH_MARGIN, 60)
            except Exception:
                self._token_expires_at = time.monotonic() + _TOKEN_EXPIRY_SHORT - _TOKEN_REFRESH_MARGIN
        else:
            self._token_expires_at = time.monotonic() + _TOKEN_EXPIRY_SHORT - _TOKEN_REFRESH_MARGIN

        logger.debug("Sameday token acquired, expires in ~%.0fs", self._token_expires_at - time.monotonic())
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        """Make an authenticated API call, injecting the X-Auth-Token header."""
        token = self._ensure_token()
        headers: dict[str, str] = {"X-Auth-Token": token}
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

    # ── AWB ──

    def generate_awb(self, payload: dict[str, Any]) -> dict:
        """POST /awb — generate an AWB."""
        return self._call("POST", "awb", json=payload)

    def delete_parcel(self, awb_number: str) -> bool:
        """DELETE /awb/{awb_number} — cancel/delete a parcel."""
        self._call("DELETE", f"awb/{awb_number}")
        return True

    def download_awb(self, awb_number: str, format: str = "A4") -> bytes:
        """GET /awb/download/{awb_number}/{format}/pdf/inline — download AWB label as PDF."""
        response = self.http.call(
            "GET",
            f"awb/download/{awb_number}/{format}/pdf/inline",
            headers={"X-Auth-Token": self._ensure_token()},
            direct_response=True,
        )
        return response.content if hasattr(response, "content") else b""

    # ── Tracking ──

    def get_parcel_status(self, parcel_number: str) -> dict:
        """GET /client/parcel/{parcel_number}001/status-history — get tracking history."""
        return self._call("GET", f"client/parcel/{parcel_number}001/status-history")

    # ── Pickup Points ──

    def get_pickup_points(self) -> list:
        """GET /client/pickup-points — list available pickup points."""
        response = self._call("GET", "client/pickup-points")
        if isinstance(response, dict):
            return response.get("pickupPoints", [])
        return response if isinstance(response, list) else []

    # ── AWB List ──

    def get_awb_list(self, page: int = 1, per_page: int = 50, **kwargs) -> dict:
        """GET /client-awb-list — list AWBs with pagination."""
        params: dict[str, Any] = {
            "page": page,
            "countPerPage": per_page,
        }
        if extra_params := kwargs.pop("params", None):
            params.update(extra_params)
        return self._call("GET", "client-awb-list", params=params, **kwargs)
