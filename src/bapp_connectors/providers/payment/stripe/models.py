"""
Pydantic models for Stripe API request/response payloads.

These model the raw Stripe API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Request models ──


class StripeCheckoutLineItem(BaseModel):
    """A single line item for a Stripe checkout session."""

    price_data: dict | None = None
    quantity: int = 1


class StripeCheckoutSessionCreate(BaseModel):
    """Parameters for creating a Stripe checkout session."""

    mode: str = "payment"
    success_url: str | None = None
    cancel_url: str | None = None
    customer_email: str | None = None
    line_items: list[StripeCheckoutLineItem] = []
    metadata: dict = {}

    model_config = {"populate_by_name": True}


class StripeRefundCreate(BaseModel):
    """Parameters for creating a Stripe refund."""

    payment_intent: str
    amount: int | None = None  # in smallest currency unit (cents)
    reason: str | None = None

    model_config = {"populate_by_name": True}


# ── Response models ──


class StripeCheckoutSession(BaseModel):
    """Stripe checkout session response."""

    id: str = ""
    url: str | None = None
    amount_total: int | None = None
    currency: str = ""
    status: str | None = None
    payment_intent: str | None = None
    customer_email: str | None = None
    expires_at: int | None = None
    metadata: dict = {}

    model_config = {"populate_by_name": True}


class StripePaymentIntent(BaseModel):
    """Stripe payment intent response."""

    id: str = ""
    status: str = ""
    amount: int = 0
    currency: str = ""
    payment_method_types: list[str] = Field(default_factory=list)
    latest_charge: str | None = None
    created: int = 0
    metadata: dict = {}

    model_config = {"populate_by_name": True}


class StripeRefund(BaseModel):
    """Stripe refund response."""

    id: str = ""
    payment_intent: str | None = None
    amount: int = 0
    currency: str = ""
    status: str = ""
    reason: str | None = None
    created: int = 0
    metadata: dict = {}

    model_config = {"populate_by_name": True}
