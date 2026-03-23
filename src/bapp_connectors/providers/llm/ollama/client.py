"""
Ollama API client — raw HTTP calls only, no business logic.

Ollama exposes a local HTTP API at http://localhost:11434.
No authentication required.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class OllamaApiClient:
    """
    Low-level Ollama API client.

    Endpoints:
        POST /api/chat        — chat completion
        GET  /api/tags        — list local models
        POST /api/embed       — generate embeddings
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def test_auth(self) -> bool:
        """Verify Ollama is reachable by listing models."""
        try:
            self.http.call("GET", "api/tags")
            return True
        except Exception:
            return False

    def chat(self, payload: dict) -> dict:
        """POST /api/chat — chat completion (stream: false)."""
        payload.setdefault("stream", False)
        return self.http.call("POST", "api/chat", json=payload)

    def list_models(self) -> dict:
        """GET /api/tags — list available local models."""
        return self.http.call("GET", "api/tags")

    def embed(self, payload: dict) -> dict:
        """POST /api/embed — generate embeddings."""
        return self.http.call("POST", "api/embed", json=payload)
