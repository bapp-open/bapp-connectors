"""
WebDAV-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
)


class WebDAVError(ProviderError):
    """Base WebDAV error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class WebDAVServerError(WebDAVError):
    """WebDAV server returned an error."""


def classify_webdav_error(status_code: int, body: str = "", response=None) -> WebDAVError:
    """Map a WebDAV HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"WebDAV authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 403:
        raise PermanentProviderError(f"WebDAV forbidden: {body[:500]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"WebDAV client error {status_code}: {body[:500]}", status_code=status_code)
    raise WebDAVServerError(f"WebDAV server error {status_code}: {body[:500]}", response=response)
