"""
RoboSMS API client — raw HTTP calls only, no business logic.

Extends ResilientHttpClient for retry, rate limiting, and auth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class RoboSMSApiClient:
    """
    Low-level RoboSMS API client.

    This class only handles HTTP calls and response parsing.
    """

    def __init__(self, http_client: ResilientHttpClient, device_id: str = ""):
        self.http = http_client
        self.device_id = device_id

        self._extra_headers = {
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, **kwargs) -> dict | list | str:
        headers = dict(self._extra_headers)
        if extra := kwargs.pop("headers", None):
            headers.update(extra)
        return self.http.call(method, path, headers=headers, **kwargs)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Test authentication by sending a dummy SMS to an invalid number."""
        try:
            self.send_sms("00", "000")
        except Exception as e:
            # A 400 means auth worked but the request was invalid (expected)
            return "400" in str(e)
        return True

    # ── SMS ──

    def send_sms(self, to: str, content: str, device_id: str | None = None) -> dict | list | str:
        """Send a single SMS message."""
        payload: dict[str, Any] = {
            "to": to,
            "content": content,
        }
        effective_device_id = device_id or self.device_id
        if effective_device_id:
            payload["device_id"] = effective_device_id
        return self._call("POST", "sms/", json=payload)
