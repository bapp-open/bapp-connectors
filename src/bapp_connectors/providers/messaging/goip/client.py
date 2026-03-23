"""
GoIP SMS gateway API client — raw HTTP calls only, no business logic.

GoIP devices expose a simple HTTP interface:
  - GET /send.html?n={to}&m={message}&l={line}&u={user}&p={pass}
  - GET /status.html (device status)
  - GET /send_status.xml (send queue status)

Uses HTTP Basic Auth for the web interface.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class GoIPApiClient:
    """
    Low-level GoIP device API client.

    This class only handles HTTP calls and response parsing.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        username: str,
        password: str,
        line: int = 1,
        max_retries: int = 0,
    ):
        self.http = http_client
        self._username = username
        self._password = password
        self._line = line
        self._max_retries = max_retries

    def _get_text(self, path: str, **kwargs) -> str:
        """Make a GET request and return response as text."""
        response = self.http.call("GET", path, direct_response=True, **kwargs)
        return response.content.decode() if hasattr(response, "content") else str(response)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """Verify credentials by checking the device status page."""
        try:
            content = self._get_text("status.html")
            return "uptime:" in content.lower()
        except Exception:
            return False

    # ── SMS ──

    def send_sms(self, to: str, message: str, line: int | None = None, retries: int = 0) -> bool:
        """
        Send an SMS via the GoIP device.

        Returns True on success, False if the line stayed busy after max retries.
        Raises Exception on other errors.
        """
        if len(message) >= 3000:
            raise ValueError("Message must be less than 3000 characters")

        effective_line = line or self._line
        params = {
            "n": to,
            "m": message,
            "l": effective_line,
            "u": self._username,
            "p": self._password,
        }
        content = self._get_text("send.html", params=params).lower().strip()

        if "sending" in content:
            return True
        if "busy" in content:
            if retries >= self._max_retries:
                return False
            time.sleep(1)
            return self.send_sms(to, message, line=effective_line, retries=retries + 1)
        raise RuntimeError(f"GoIP send error: {content}")

    # ── Status ──

    def get_send_status(self) -> str:
        """GET /send_status.xml — get the send queue status."""
        return self._get_text("send_status.xml")

    # ── History Management ──

    def clear_received_history(self, line: int = -1) -> bool:
        """Clear received SMS history on the device."""
        response = self.http.call(
            "GET", f"tools.html?action=del&type=sms_inbox&line={line}&pos=-1", direct_response=True,
        )
        return response.status_code == 200

    def clear_sent_history(self, line: int = -1) -> bool:
        """Clear sent SMS history on the device."""
        response = self.http.call(
            "GET", f"tools.html?action=del&type=sms_outbox&line={line}&pos=-1", direct_response=True,
        )
        return response.status_code == 200
