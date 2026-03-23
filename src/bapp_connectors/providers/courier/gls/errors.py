"""
GLS-specific error mapping.

Maps GLS API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class GLSError(ProviderError):
    """Base GLS error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class GLSAPIError(GLSError):
    """GLS returned an API error."""


def classify_gls_error(status_code: int, body: str = "", response=None) -> GLSError:
    """Map a GLS HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"GLS authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("GLS rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"GLS client error {status_code}: {body[:500]}", status_code=status_code)
    raise GLSAPIError(f"GLS server error {status_code}: {body[:500]}", response=response)
