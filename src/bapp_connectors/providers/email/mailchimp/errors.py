"""
Mandrill-specific error mapping.

Maps Mandrill API errors to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
)


class MandrillError(ProviderError):
    """Base Mandrill error."""


class MandrillAPIError(MandrillError):
    """Mandrill API returned an error response."""


class MandrillConnectionError(MandrillError):
    """Failed to connect to Mandrill API."""

    retryable = True


def classify_mandrill_error(exc: Exception) -> ConnectorError:
    """
    Map a Mandrill exception to the appropriate framework error.

    Checks the error message for known patterns:
    - ``Invalid_Key`` → AuthenticationError
    - Connection / timeout issues → MandrillConnectionError (retryable)
    - Everything else → MandrillAPIError
    """
    msg = str(exc)
    msg_lower = msg.lower()

    if "invalid_key" in msg_lower or "invalid key" in msg_lower:
        return AuthenticationError(f"Mandrill authentication failed: {msg}")
    if "authentication" in msg_lower or "401" in msg:
        return AuthenticationError(f"Mandrill authentication failed: {msg}")
    if "connection" in msg_lower or "timed out" in msg_lower or "timeout" in msg_lower:
        return MandrillConnectionError(f"Mandrill connection error: {msg}")
    return MandrillAPIError(f"Mandrill API error: {msg}")
