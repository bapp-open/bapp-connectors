"""Ollama-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import PermanentProviderError, ProviderError


class OllamaError(ProviderError):
    """Base Ollama error."""


class OllamaConnectionError(OllamaError):
    """Cannot reach the Ollama server."""


def classify_ollama_error(status_code: int, body: str = "", response=None) -> OllamaError:
    """Map an Ollama HTTP error to the appropriate framework error."""
    if status_code == 404:
        raise PermanentProviderError(f"Ollama model not found: {body[:200]}", status_code=404)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Ollama client error {status_code}: {body[:500]}", status_code=status_code)
    raise OllamaError(f"Ollama server error {status_code}: {body[:500]}")
