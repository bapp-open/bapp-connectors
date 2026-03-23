"""
CEL.ro-specific error mapping.

Maps CEL API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class CelError(ProviderError):
    """Base CEL error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class CelAPIError(CelError):
    """CEL returned an API error."""


class CelAuthenticationError(CelError):
    """CEL authentication failed (invalid credentials or token)."""

    retryable = False


def classify_cel_error(status_code: int, body: str = "", response=None) -> CelError:
    """Map a CEL HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"CEL authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("CEL rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"CEL client error {status_code}: {body[:500]}", status_code=status_code)
    raise CelAPIError(f"CEL server error {status_code}: {body[:500]}", response=response)
