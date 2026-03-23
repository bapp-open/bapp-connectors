"""
Anthropic API client — raw HTTP calls only, no business logic.

Auth is via x-api-key header + anthropic-version header, handled by MultiHeaderAuth.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class AnthropicApiClient:
    """
    Low-level Anthropic API client.

    Endpoints:
        POST /messages — create a message (chat completion)
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def test_auth(self) -> bool:
        """Verify credentials by sending a minimal message request."""
        try:
            self.http.call("POST", "messages", json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            })
            return True
        except Exception:
            return False

    def create_message(self, payload: dict) -> dict:
        """POST /messages — create a chat completion."""
        return self.http.call("POST", "messages", json=payload)
