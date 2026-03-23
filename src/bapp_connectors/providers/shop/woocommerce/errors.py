"""
WooCommerce-specific error mapping.

Maps WooCommerce API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class WooCommerceError(ProviderError):
    """Base WooCommerce error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class WooCommerceAPIError(WooCommerceError):
    """WooCommerce returned an API error."""


def classify_woocommerce_error(status_code: int, body: str = "", response=None) -> WooCommerceError:
    """Map a WooCommerce HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(f"WooCommerce authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("WooCommerce rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"WooCommerce client error {status_code}: {body[:500]}", status_code=status_code)
    raise WooCommerceAPIError(f"WooCommerce server error {status_code}: {body[:500]}", response=response)
