"""
WhatsApp-specific error mapping.

Maps WhatsApp Cloud API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class WhatsAppError(ProviderError):
    """Base WhatsApp error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class WhatsAppAPIError(WhatsAppError):
    """WhatsApp returned an API error."""


def classify_whatsapp_error(status_code: int, body: str = "", response=None) -> WhatsAppError:
    """Map a WhatsApp HTTP error to the appropriate framework error."""
    if status_code in (401, 403):
        raise AuthenticationError(f"WhatsApp authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("WhatsApp rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"WhatsApp client error {status_code}: {body[:500]}", status_code=status_code)
    raise WhatsAppAPIError(f"WhatsApp server error {status_code}: {body[:500]}", response=response)
