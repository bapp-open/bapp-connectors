"""Gemini-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class GeminiError(ProviderError):
    """Base Gemini error."""


class GeminiAPIError(GeminiError):
    """Gemini returned an API error."""


def classify_gemini_error(status_code: int, body: str = "", response=None) -> GeminiError:
    """Map a Gemini HTTP error to the appropriate framework error."""
    if status_code in (401, 403):
        raise AuthenticationError(f"Gemini authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Gemini rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Gemini client error {status_code}: {body[:500]}", status_code=status_code)
    raise GeminiAPIError(f"Gemini server error {status_code}: {body[:500]}")
