"""
Mandrill API client — raw HTTP calls only, no business logic.

Auth is via API key injected into every JSON POST body.
Mandrill requires all requests to be POST with ``{"key": "<api_key>"}``
merged into the payload.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class MandrillApiClient:
    """
    Low-level Mandrill API client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.

    Every Mandrill endpoint is a POST with ``{"key": api_key, ...}`` in the body.
    """

    def __init__(self, http_client: ResilientHttpClient, api_key: str):
        self.http = http_client
        self._api_key = api_key

    def _call(self, path: str, payload: dict | None = None) -> dict | list | str:
        """
        POST to a Mandrill API endpoint with the API key injected.

        Args:
            path: Endpoint path relative to base_url (e.g. ``"users/ping.json"``).
            payload: Additional JSON fields to send. The ``key`` field is added
                automatically.

        Returns:
            Parsed JSON response (dict, list, or string).
        """
        body: dict = {"key": self._api_key}
        if payload:
            body.update(payload)
        return self.http.post(path, json=body)

    # ── Auth / Connection Test ──

    def test_auth(self) -> bool:
        """
        Verify the API key by calling ``users/ping.json``.

        Mandrill returns the literal string ``"PONG!"`` on success.
        """
        try:
            response = self._call("users/ping.json")
            return response == "PONG!"
        except Exception:
            return False

    # ── Sending ──

    def send_message(self, message: dict) -> list[dict]:
        """
        Send a single email via ``messages/send.json``.

        Args:
            message: Mandrill ``message`` object (to, subject, text, html, etc.).

        Returns:
            List of per-recipient result dicts from Mandrill.
        """
        result = self._call("messages/send.json", {"message": message})
        if isinstance(result, list):
            return result
        return [result] if isinstance(result, dict) else []

    def send_template(
        self,
        template_name: str,
        template_content: list[dict],
        message: dict,
    ) -> list[dict]:
        """
        Send an email using a Mandrill template via ``messages/send-template.json``.

        Args:
            template_name: Slug of the Mandrill template to use.
            template_content: List of ``{"name": ..., "content": ...}`` blocks for
                editable template regions.
            message: Mandrill ``message`` object.

        Returns:
            List of per-recipient result dicts from Mandrill.
        """
        result = self._call(
            "messages/send-template.json",
            {
                "template_name": template_name,
                "template_content": template_content,
                "message": message,
            },
        )
        if isinstance(result, list):
            return result
        return [result] if isinstance(result, dict) else []
