"""
SES-specific error mapping.

Maps boto3 ClientError codes to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    ConnectorError,
    ProviderError,
)


class SESError(ProviderError):
    """Base SES error."""


class SESConnectionError(SESError):
    """SES connection/throttling error — retryable."""

    retryable = True


def classify_ses_error(exc: Exception) -> ConnectorError:
    """
    Map a boto3 ClientError to the appropriate framework error.

    Parses the error code from the exception string for classification.
    """
    msg = str(exc)

    # Auth-related errors
    auth_codes = ("InvalidClientTokenId", "SignatureDoesNotMatch", "AccessDenied", "AccessDeniedException")
    for code in auth_codes:
        if code in msg:
            return AuthenticationError(f"SES authentication failed: {msg[:200]}")

    # Throttling errors — retryable
    throttle_codes = ("Throttling", "TooManyRequests", "TooManyRequestsException")
    for code in throttle_codes:
        if code in msg:
            return SESConnectionError(f"SES throttled: {msg[:200]}")

    # Message rejected — not retryable
    if "MessageRejected" in msg:
        return SESError(f"SES message rejected: {msg[:500]}", retryable=False)

    return SESError(f"SES error: {msg[:500]}")
