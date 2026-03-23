"""
Trendyol-specific error mapping.

Maps Trendyol API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class TrendyolError(ProviderError):
    """Base Trendyol error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class TrendyolAPIError(TrendyolError):
    """Trendyol returned an API error."""


def classify_trendyol_error(status_code: int, body: str = "", response=None) -> TrendyolError:
    """Map a Trendyol HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Trendyol authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Trendyol rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Trendyol client error {status_code}: {body[:500]}", status_code=status_code)
    raise TrendyolAPIError(f"Trendyol server error {status_code}: {body[:500]}", response=response)
