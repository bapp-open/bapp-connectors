"""
Vendigo-specific error mapping.

Maps Vendigo API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class VendigoError(ProviderError):
    """Base Vendigo error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class VendigoAPIError(VendigoError):
    """Vendigo returned an API error."""


def classify_vendigo_error(status_code: int, body: str = "", response=None) -> VendigoError:
    """Map a Vendigo HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Vendigo authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Vendigo rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Vendigo client error {status_code}: {body[:500]}", status_code=status_code)
    raise VendigoAPIError(f"Vendigo server error {status_code}: {body[:500]}", response=response)
