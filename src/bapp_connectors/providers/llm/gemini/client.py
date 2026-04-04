"""
Google Gemini API client — raw HTTP calls only, no business logic.

Auth is via x-goog-api-key header.
Endpoints use model name in the URL path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class GeminiApiClient:
    """
    Low-level Gemini API client.

    Endpoints:
        POST /models/{model}:generateContent     — chat completion
        GET  /models                               — list models
        POST /models/{model}:embedContent          — embeddings
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def test_auth(self) -> bool:
        """Verify credentials by listing models."""
        try:
            self.http.call("GET", "models")
            return True
        except Exception:
            return False

    def generate_content(self, model: str, payload: dict, timeout: int | None = None) -> dict:
        """POST /models/{model}:generateContent — generate a response."""
        kwargs: dict = {"json": payload}
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self.http.call("POST", f"models/{model}:generateContent", **kwargs)

    def list_models(self) -> dict:
        """GET /models — list available models."""
        return self.http.call("GET", "models")

    def embed_content(self, model: str, payload: dict) -> dict:
        """POST /models/{model}:embedContent — generate embeddings."""
        return self.http.call("POST", f"models/{model}:embedContent", json=payload)
