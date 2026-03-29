"""
Normalized DTOs for saved payment methods and customer management.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .base import BaseDTO
from .payment import PaymentMethodType


class CardBrand(StrEnum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    DINERS = "diners"
    JCB = "jcb"
    UNIONPAY = "unionpay"
    UNKNOWN = "unknown"


class SavedPaymentMethod(BaseDTO):
    """A saved payment method (card, bank account, etc.)."""

    payment_method_id: str
    customer_id: str = ""
    method_type: PaymentMethodType = PaymentMethodType.CARD
    card_brand: CardBrand = CardBrand.UNKNOWN
    last_four: str = ""
    expiry_month: int | None = None
    expiry_year: int | None = None
    is_default: bool = False
    created_at: datetime | None = None
    extra: dict = {}
