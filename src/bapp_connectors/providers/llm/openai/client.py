"""
OpenAI API client — raw HTTP calls only, no business logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class OpenAIApiClient:
    """
    Low-level OpenAI API client.

    Endpoints:
        POST /chat/completions
        GET  /models
        POST /embeddings
        POST /audio/transcriptions
        POST /images/generations
        POST /images/edits
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

    def chat_completion(self, payload: dict) -> dict:
        """POST /chat/completions — create a chat completion."""
        return self.http.call("POST", "chat/completions", json=payload)

    def list_models(self) -> dict:
        """GET /models — list available models."""
        return self.http.call("GET", "models")

    def create_embedding(self, payload: dict) -> dict:
        """POST /embeddings — create embeddings."""
        return self.http.call("POST", "embeddings", json=payload)

    def create_transcription(
        self,
        audio: bytes,
        model: str = "whisper-1",
        language: str | None = None,
        response_format: str = "verbose_json",
        filename: str = "audio.mp3",
        **kwargs,
    ) -> dict | str:
        """POST /audio/transcriptions — transcribe audio (Whisper).

        Uses multipart/form-data. The http client sends this as `files` + `data`.
        """
        files = {"file": (filename, audio)}
        data: dict = {"model": model, "response_format": response_format}
        if language:
            data["language"] = language
        data.update(kwargs)
        return self.http.call("POST", "audio/transcriptions", files=files, data=data)

    def create_image(self, payload: dict) -> dict:
        """POST /images/generations — generate an image from a prompt."""
        return self.http.call("POST", "images/generations", json=payload, timeout=60)

    def edit_image(self, image: bytes, prompt: str, model: str = "gpt-image-1", size: str = "1024x1024", **kwargs) -> dict:
        """POST /images/edits — edit an image with a prompt (multipart form data)."""
        files = {"image": ("image.png", image, "image/png")}
        data: dict = {"prompt": prompt, "model": model, "size": size}
        data.update(kwargs)
        return self.http.call("POST", "images/edits", files=files, data=data, timeout=60)
