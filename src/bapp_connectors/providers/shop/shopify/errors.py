"""Shopify-specific error mapping."""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
)


class ShopifyError(ProviderError):
    """Base Shopify error."""


class ShopifyAPIError(ShopifyError):
    """Shopify returned an API error."""


def classify_shopify_error(status_code: int, body: str = "", response=None) -> ShopifyError:
    if status_code in (401, 403):
        raise AuthenticationError(f"Shopify authentication failed: {body[:200]}", status_code=status_code)
    if status_code == 429:
        raise RateLimitError("Shopify rate limit exceeded")
    if status_code == 422:
        raise PermanentProviderError(f"Shopify validation error: {body[:500]}", status_code=status_code)
    if 400 <= status_code < 500:
        raise PermanentProviderError(f"Shopify client error {status_code}: {body[:500]}", status_code=status_code)
    raise ShopifyAPIError(f"Shopify server error {status_code}: {body[:500]}")
