"""
SMTP/IMAP-specific error mapping.

Maps SMTP and IMAP errors to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
)

# ── SMTP errors ──


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


# ── IMAP errors ──


class IMAPError(ProviderError):
    """Base IMAP error."""


class IMAPConnectionError(IMAPError):
    """Failed to connect to IMAP server."""

    retryable = True


class IMAPFetchError(IMAPError):
    """Failed to fetch messages from IMAP server."""


def classify_imap_error(exc: Exception) -> ConnectorError:
    """Map an IMAP exception to the appropriate framework error."""
    msg = str(exc)
    if "authentication" in msg.lower() or "login" in msg.lower():
        return AuthenticationError(f"IMAP authentication failed: {msg}")
    if "connection" in msg.lower() or "timed out" in msg.lower():
        return IMAPConnectionError(f"IMAP connection error: {msg}")
    return IMAPFetchError(f"IMAP error: {msg}")
