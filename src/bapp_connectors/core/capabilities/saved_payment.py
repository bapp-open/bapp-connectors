"""
Saved payment capability — for providers that support storing payment methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto.payment import CheckoutSession, PaymentResult
    from bapp_connectors.core.dto.saved_payment import SavedPaymentMethod


class SavedPaymentCapability(ABC):
    """Adapter supports saving and reusing payment methods.

    Flow:
    1. ``create_customer()`` — create a provider-side customer
    2. ``create_setup_checkout()`` — hosted page to collect card details
    3. ``list_payment_methods()`` — retrieve saved cards after setup
    4. ``charge_saved_method()`` — charge a saved card for returning customers
    """

    @abstractmethod
    def create_customer(
        self,
        email: str,
        name: str = "",
        metadata: dict | None = None,
    ) -> str:
        """Create a customer in the payment provider.

        Returns the provider's customer ID (e.g. Stripe ``cus_xxx``).
        """
        ...

    @abstractmethod
    def create_setup_checkout(
        self,
        customer_id: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> CheckoutSession:
        """Create a checkout session to collect card details without charging.

        Returns a CheckoutSession with a URL to redirect the customer to.
        After completing checkout, the payment method is attached to the customer.
        """
        ...

    @abstractmethod
    def list_payment_methods(self, customer_id: str) -> list[SavedPaymentMethod]:
        """List saved payment methods for a customer."""
        ...

    @abstractmethod
    def delete_payment_method(self, payment_method_id: str) -> bool:
        """Detach/remove a saved payment method. Returns True on success."""
        ...

    @abstractmethod
    def charge_saved_method(
        self,
        customer_id: str,
        payment_method_id: str,
        amount: Decimal,
        currency: str,
        description: str = "",
        metadata: dict | None = None,
    ) -> PaymentResult:
        """Charge a saved payment method directly (off-session).

        Used for returning customers who have already saved a card.
        The charge happens immediately without customer interaction.
        """
        ...

    def get_customer(self, customer_id: str) -> dict:
        """Retrieve customer details from the provider."""
        raise NotImplementedError("This provider does not support customer retrieval.")

    def set_default_payment_method(
        self, customer_id: str, payment_method_id: str,
    ) -> bool:
        """Set the default payment method for a customer."""
        raise NotImplementedError("This provider does not support setting default payment methods.")
