"""
Colete Online-specific error mapping.

Maps Colete Online API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class ColeteOnlineError(ProviderError):
    """Base Colete Online error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class ColeteOnlineAPIError(ColeteOnlineError):
    """Colete Online returned an API error."""


def classify_co_error(status_code: int, body: str = "", response=None) -> ColeteOnlineError:
    """Map a Colete Online HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Colete Online authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Colete Online rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Colete Online client error {status_code}: {body[:500]}", status_code=status_code)
    raise ColeteOnlineAPIError(f"Colete Online server error {status_code}: {body[:500]}", response=response)
