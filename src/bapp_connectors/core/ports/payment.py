"""
Payment port — the common contract for all payment adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto import BillingDetails, CheckoutSession, PaginatedResult, PaymentResult, Refund


class PaymentPort(BasePort):
    """
    Common contract for all payment adapters.

    Covers: checkout sessions, payment status, refunds, listing payments.
    """

    @abstractmethod
    def create_checkout_session(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        identifier: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        client_email: str | None = None,
        billing: BillingDetails | None = None,
    ) -> CheckoutSession:
        """Create a payment checkout session / payment link.

        Args:
            amount: Payment amount.
            currency: ISO 4217 currency code (e.g. "RON", "EUR").
            description: Human-readable description of the payment.
            identifier: Your order/invoice ID.
            success_url: Redirect URL after successful payment.
            cancel_url: Redirect URL if user cancels.
            client_email: Shorthand for billing email (deprecated, use billing).
            billing: Client billing details (name, phone, address, tax ID).
                Providers use what they support and ignore the rest.
        """
        ...

    @abstractmethod
    def get_payment(self, payment_id: str) -> PaymentResult:
        """Get the status of a payment."""
        ...

    @abstractmethod
    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        """Issue a refund for a payment (full or partial)."""
        ...

    def list_payments(
        self,
        *,
        status: str | None = None,
        created_after: int | None = None,
        created_before: int | None = None,
        limit: int = 25,
        cursor: str | None = None,
    ) -> PaginatedResult[PaymentResult]:
        """List payments with optional filters.

        Args:
            status: Filter by normalized status (e.g. "completed", "pending").
            created_after: Unix timestamp — only return payments created after this time.
            created_before: Unix timestamp — only return payments created before this time.
            limit: Max results per page (provider may cap this).
            cursor: Opaque cursor from a previous PaginatedResult for next page.

        Returns:
            PaginatedResult containing PaymentResult items.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support list_payments")
