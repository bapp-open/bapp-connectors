"""Magento-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class MagentoError(ProviderError):
    """Base Magento error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class MagentoAPIError(MagentoError):
    """Magento returned an API error."""


def classify_magento_error(status_code: int, body: str = "", response=None) -> MagentoError:
    if status_code in (401, 403):
        raise AuthenticationError(f"Magento authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Magento rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Magento client error {status_code}: {body[:500]}", status_code=status_code)
    raise MagentoAPIError(f"Magento server error {status_code}: {body[:500]}", response=response)
