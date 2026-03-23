"""
Netopia-specific error mapping.

Maps Netopia API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class NetopiaError(ProviderError):
    """Base Netopia error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class NetopiaAPIError(NetopiaError):
    """Netopia returned an API error."""


class NetopiaPaymentError(NetopiaError):
    """Netopia payment operation failed."""


def classify_netopia_error(status_code: int, body: str = "", response=None) -> NetopiaError:
    """Map a Netopia HTTP error to the appropriate framework error."""
    if status_code == 401 or status_code == 403:
        raise AuthenticationError(
            f"Netopia authentication failed: {body[:200]}",
            status_code=status_code,
        )
    if status_code == 429:
        raise RateLimitError("Netopia rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(
            f"Netopia client error {status_code}: {body[:500]}",
            status_code=status_code,
        )
    raise NetopiaAPIError(
        f"Netopia server error {status_code}: {body[:500]}",
        response=response,
    )
