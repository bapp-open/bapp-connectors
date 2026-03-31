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


class BillingDetails(BaseDTO):
    """Client billing details for checkout sessions and invoicing."""

    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    company: str = ""
    tax_id: str = ""  # CUI/CIF/VAT number
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""  # ISO 3166-1 alpha-2 (e.g. "RO")


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
