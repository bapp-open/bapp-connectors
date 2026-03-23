"""
SMTP-specific error mapping.

Maps SMTP errors to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
)


class SMTPError(ProviderError):
    """Base SMTP error."""

    def __init__(self, message: str, smtp_code: int | None = None):
        super().__init__(message)
        self.smtp_code = smtp_code


class SMTPConnectionError(SMTPError):
    """Failed to connect to SMTP server."""

    retryable = True


class SMTPSendError(SMTPError):
    """Failed to send an email."""


def classify_smtp_error(exc: Exception) -> ConnectorError:
    """Map an SMTP exception to the appropriate framework error."""
    msg = str(exc)
    if "authentication" in msg.lower() or "login" in msg.lower() or "535" in msg:
        return AuthenticationError(f"SMTP authentication failed: {msg}")
    if "connection" in msg.lower() or "timed out" in msg.lower():
        return SMTPConnectionError(f"SMTP connection error: {msg}")
    return SMTPSendError(f"SMTP error: {msg}")
