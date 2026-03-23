"""
Normalized DTOs for payment operations.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO


class PaymentMethodType(StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"
    CASH = "cash"
    OTHER = "other"


class CheckoutSession(BaseDTO):
    """A payment checkout session / payment link."""

    session_id: str
    payment_url: str
    amount: Decimal
    currency: str
    description: str = ""
    expires_at: datetime | None = None
    extra: dict = {}


class PaymentResult(BaseDTO):
    """Result of a completed payment."""

    payment_id: str
    status: str  # provider-specific, normalized via extra
    amount: Decimal
    currency: str
    method: PaymentMethodType | None = None
    paid_at: datetime | None = None
    extra: dict = {}


class Refund(BaseDTO):
    """Normalized refund."""

    refund_id: str
    payment_id: str
    amount: Decimal
    currency: str
    reason: str = ""
    status: str = ""
    created_at: datetime | None = None
    extra: dict = {}
