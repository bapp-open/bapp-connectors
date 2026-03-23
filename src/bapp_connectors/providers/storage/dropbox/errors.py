"""
Dropbox-specific error mapping.

Maps Dropbox API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class DropboxError(ProviderError):
    """Base Dropbox error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class DropboxAPIError(DropboxError):
    """Dropbox returned an API error."""


class DropboxPathNotFoundError(DropboxError):
    """Dropbox path not found (409 with path/not_found)."""

    retryable = False


def classify_dropbox_error(status_code: int, body: str = "", response=None) -> DropboxError:
    """Map a Dropbox HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Dropbox authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Dropbox rate limit exceeded")
    if status_code == 409:
        if "path/not_found" in body:
            raise DropboxPathNotFoundError(f"Dropbox path not found: {body[:500]}", response=response)
        raise PermanentProviderError(f"Dropbox conflict error: {body[:500]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Dropbox client error {status_code}: {body[:500]}", status_code=status_code)
    raise DropboxAPIError(f"Dropbox server error {status_code}: {body[:500]}", response=response)
