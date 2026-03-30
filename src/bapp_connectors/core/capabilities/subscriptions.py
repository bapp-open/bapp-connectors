"""
Subscription capability — optional interface for providers that support recurring billing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from bapp_connectors.core.dto.payment import CheckoutSession
    from bapp_connectors.core.dto.subscription import Subscription


class SubscriptionCapability(ABC):
    """Adapter supports creating and managing recurring subscriptions."""

    @abstractmethod
    def create_subscription_checkout(
        self,
        price_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        customer_email: str | None = None,
        trial_days: int | None = None,
        metadata: dict | None = None,
    ) -> CheckoutSession:
        """Create a checkout session for a subscription plan.

        Uses the provider's hosted checkout to collect payment details and
        start the subscription. Returns a CheckoutSession with the URL to
        redirect the customer to.

        Args:
            price_id: Provider-specific recurring price/plan identifier.
            success_url: URL to redirect after successful checkout.
            cancel_url: URL to redirect if the customer cancels.
            customer_email: Pre-fill the customer's email on checkout.
            trial_days: Number of free trial days before billing starts.
            metadata: Arbitrary key-value pairs stored on the subscription.
        """
        ...

    @abstractmethod
    def get_subscription(self, subscription_id: str) -> Subscription:
        """Retrieve a subscription by ID."""
        ...

    @abstractmethod
    def cancel_subscription(self, subscription_id: str, immediate: bool = False) -> Subscription:
        """Cancel a subscription.

        Args:
            subscription_id: The subscription to cancel.
            immediate: If True, cancel immediately. If False (default),
                       cancel at the end of the current billing period.
        """
        ...

    def update_subscription(self, subscription_id: str, price_id: str) -> Subscription:
        """Change a subscription to a different plan/price."""
        raise NotImplementedError("This provider does not support subscription updates via API.")

    def pause_subscription(self, subscription_id: str) -> Subscription:
        """Pause billing on a subscription."""
        raise NotImplementedError("This provider does not support pausing subscriptions.")

    def resume_subscription(self, subscription_id: str) -> Subscription:
        """Resume a paused subscription."""
        raise NotImplementedError("This provider does not support resuming subscriptions.")
