"""
PrestaShop-specific error mapping.

Maps PrestaShop API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class PrestaShopError(ProviderError):
    """Base PrestaShop error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class PrestaShopAPIError(PrestaShopError):
    """PrestaShop returned an API error."""


class PrestaShopAuthenticationError(PrestaShopError):
    """PrestaShop authentication failed (invalid API key or insufficient permissions)."""

    retryable = False


def classify_prestashop_error(status_code: int, body: str = "", response=None) -> PrestaShopError:
    """Map a PrestaShop HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"PrestaShop authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 403:
        raise AuthenticationError(
            f"PrestaShop access denied (check API key permissions): {body[:200]}",
            status_code=status_code,
        )
    if status_code == 429:
        raise RateLimitError("PrestaShop rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"PrestaShop client error {status_code}: {body[:500]}", status_code=status_code)
    raise PrestaShopAPIError(f"PrestaShop server error {status_code}: {body[:500]}", response=response)
