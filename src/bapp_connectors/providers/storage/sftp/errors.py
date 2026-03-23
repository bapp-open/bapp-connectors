"""
SFTP-specific error mapping.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
)


class SFTPError(ProviderError):
    """Base SFTP error."""


class SFTPConnectionError(SFTPError):
    """Failed to connect to the SFTP server."""


def classify_sftp_error(exception: Exception) -> SFTPError:
    """Map an SFTP/SSH exception to the appropriate framework error."""
    msg = str(exception)
    if "authentication" in msg.lower() or "auth" in msg.lower():
        raise AuthenticationError(f"SFTP authentication failed: {msg[:200]}")
    if "no such file" in msg.lower() or "not found" in msg.lower():
        raise PermanentProviderError(f"SFTP file not found: {msg[:200]}")
    if "permission" in msg.lower():
        raise PermanentProviderError(f"SFTP permission denied: {msg[:200]}")
    raise SFTPConnectionError(f"SFTP error: {msg[:500]}")
