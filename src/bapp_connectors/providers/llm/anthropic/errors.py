"""
Anthropic-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class AnthropicError(ProviderError):
    """Base Anthropic error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class AnthropicAPIError(AnthropicError):
    """Anthropic returned an API error."""


def classify_anthropic_error(status_code: int, body: str = "", response=None) -> AnthropicError:
    """Map an Anthropic HTTP error to the appropriate framework error."""
    if status_code in (401, 403):
        raise AuthenticationError(f"Anthropic authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Anthropic rate limit exceeded")
    if status_code == 529:
        raise ProviderError("Anthropic API overloaded", status_code=529)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Anthropic client error {status_code}: {body[:500]}", status_code=status_code)
    raise AnthropicAPIError(f"Anthropic server error {status_code}: {body[:500]}", response=response)
