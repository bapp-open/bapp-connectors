"""
Payment port — the common contract for all payment adapters.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto import CheckoutSession, PaymentResult, Refund


class PaymentPort(BasePort):
    """
    Common contract for all payment adapters.

    Covers: checkout sessions, payment status, refunds.
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
    ) -> CheckoutSession:
        """Create a payment checkout session / payment link."""
        ...

    @abstractmethod
    def get_payment(self, payment_id: str) -> PaymentResult:
        """Get the status of a payment."""
        ...

    @abstractmethod
    def refund(self, payment_id: str, amount: Decimal | None = None, reason: str = "") -> Refund:
        """Issue a refund for a payment (full or partial)."""
        ...
