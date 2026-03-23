"""
OpenAI-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class OpenAIError(ProviderError):
    """Base OpenAI error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class OpenAIAPIError(OpenAIError):
    """OpenAI returned an API error."""


def classify_openai_error(status_code: int, body: str = "", response=None) -> OpenAIError:
    """Map an OpenAI HTTP error to the appropriate framework error."""
    if status_code in (401, 403):
        raise AuthenticationError(f"OpenAI authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("OpenAI rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"OpenAI client error {status_code}: {body[:500]}", status_code=status_code)
    raise OpenAIAPIError(f"OpenAI server error {status_code}: {body[:500]}", response=response)
