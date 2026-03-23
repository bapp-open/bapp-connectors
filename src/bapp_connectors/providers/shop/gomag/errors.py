"""
Gomag-specific error mapping.

Maps Gomag API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class GomagError(ProviderError):
    """Base Gomag error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class GomagAPIError(GomagError):
    """Gomag returned an API error."""


def classify_gomag_error(status_code: int, body: str = "", response=None) -> GomagError:
    """Map a Gomag HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Gomag authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Gomag rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Gomag client error {status_code}: {body[:500]}", status_code=status_code)
    raise GomagAPIError(f"Gomag server error {status_code}: {body[:500]}", response=response)
