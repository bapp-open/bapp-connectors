"""
Gmail-specific error mapping.

Maps Gmail API errors to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
    RateLimitError,
)


class GmailError(ProviderError):
    """Base Gmail error."""


class GmailConnectionError(GmailError):
    """Failed to connect to Gmail API."""

    retryable = True


def classify_gmail_error(exc: Exception) -> ConnectorError:
    """
    Map a Gmail exception to the appropriate framework error.

    Checks the error message for known patterns:
    - Auth / 401 / 403 -> AuthenticationError
    - 429 / rate limit -> RateLimitError (retryable)
    - Connection / timeout -> GmailConnectionError (retryable)
    - Everything else -> GmailError
    """
    msg = str(exc)
    msg_lower = msg.lower()

    if "401" in msg or "403" in msg or "invalid credentials" in msg_lower:
        return AuthenticationError(f"Gmail authentication failed: {msg}")
    if "authentication" in msg_lower or "unauthorized" in msg_lower:
        return AuthenticationError(f"Gmail authentication failed: {msg}")
    if "429" in msg or "rate limit" in msg_lower or "quota" in msg_lower:
        return RateLimitError(f"Gmail rate limited: {msg}")
    if "connection" in msg_lower or "timed out" in msg_lower or "timeout" in msg_lower:
        return GmailConnectionError(f"Gmail connection error: {msg}")
    return GmailError(f"Gmail API error: {msg}")
