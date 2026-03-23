"""
Telegram-specific error mapping.

Maps Telegram Bot API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class TelegramError(ProviderError):
    """Base Telegram error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class TelegramAPIError(TelegramError):
    """Telegram returned an API error."""


def classify_telegram_error(status_code: int, body: str = "", response=None) -> TelegramError:
    """Map a Telegram HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"Telegram bot token invalid: {body[:200]}", status_code=status_code)
    if status_code == 403:
        raise PermanentProviderError(f"Telegram forbidden (bot blocked or chat not found): {body[:500]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Telegram rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Telegram client error {status_code}: {body[:500]}", status_code=status_code)
    raise TelegramAPIError(f"Telegram server error {status_code}: {body[:500]}", response=response)
