"""
Stripe-specific error mapping.

Maps Stripe API error responses to framework error types.
"""

from __future__ import annotations

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    WebhookVerificationError,
)


class StripeError(ProviderError):
    """Base Stripe error."""

    def __init__(self, message: str, response=None):
        status_code = response.status_code if response else None
        super().__init__(message, status_code=status_code)
        self.response = response


class StripeAPIError(StripeError):
    """Stripe returned an API error."""


class StripeWebhookError(WebhookVerificationError):
    """Stripe webhook signature verification failed."""


def classify_stripe_error(status_code: int, body: str = "", response=None) -> StripeError:
    """Map a Stripe HTTP error to the appropriate framework error."""
    if status_code == 401:
        raise AuthenticationError(
            f"Stripe authentication failed: {body[:200]}",
            status_code=status_code,
        )
    if status_code == 429:
        raise RateLimitError("Stripe rate limit exceeded")
    if 400 <= status_code < 500:
        raise PermanentProviderError(
            f"Stripe client error {status_code}: {body[:500]}",
            status_code=status_code,
        )
    raise StripeAPIError(
        f"Stripe server error {status_code}: {body[:500]}",
        response=response,
    )
