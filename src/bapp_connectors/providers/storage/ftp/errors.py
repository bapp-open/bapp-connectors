"""
FTP-specific error mapping.

Maps FTP errors to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
)


class FTPError(ProviderError):
    """Base FTP error."""

    def __init__(self, message: str, ftp_code: int | None = None):
        super().__init__(message)
        self.ftp_code = ftp_code


class FTPConnectionError(FTPError):
    """Failed to connect to FTP server."""

    retryable = True


class FTPPermissionError(FTPError):
    """FTP permission denied."""

    retryable = False


def classify_ftp_error(exc: Exception) -> ConnectorError:
    """Map an FTP exception to the appropriate framework error."""
    msg = str(exc)
    if "530" in msg or "login" in msg.lower() or "authentication" in msg.lower():
        return AuthenticationError(f"FTP authentication failed: {msg}")
    if "550" in msg or "permission" in msg.lower():
        return FTPPermissionError(f"FTP permission error: {msg}")
    if "connection" in msg.lower() or "timed out" in msg.lower():
        return FTPConnectionError(f"FTP connection error: {msg}")
    return FTPError(f"FTP error: {msg}")
