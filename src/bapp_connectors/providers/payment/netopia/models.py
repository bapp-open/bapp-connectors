"""
Pydantic models for Netopia API request/response payloads.

These model the raw Netopia API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Request models ──


class NetopiaBillingData(BaseModel):
    """Billing data for a Netopia payment."""

    email: str = ""
    phone: str = ""
    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")
    city: str = ""
    country: int = 1
    country_name: str = Field("Romania", alias="countryName")
    state: str = ""
    postal_code: str = Field("", alias="postalCode")
    details: str = ""

    model_config = {"populate_by_name": True}


class NetopiaShippingData(BaseModel):
    """Shipping data for a Netopia payment."""

    email: str = ""
    phone: str = ""
    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")
    city: str = ""
    country: int = 0
    country_name: str = Field("", alias="countryName")
    state: str = ""
    postal_code: str = Field("", alias="postalCode")
    details: str = ""

    model_config = {"populate_by_name": True}


class NetopiaOrderData(BaseModel):
    """Order data for a Netopia payment request."""

    order_id: str = Field("", alias="orderID")
    description: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "RON"
    date_time: str = Field("", alias="dateTime")
    billing: NetopiaBillingData = Field(default_factory=NetopiaBillingData)
    shipping: NetopiaShippingData = Field(default_factory=NetopiaShippingData)
    products: list[dict] = []
    installments: dict = Field(default_factory=lambda: {"selected": 0, "available": []})
    data: dict = {}

    model_config = {"populate_by_name": True}


class NetopiaPaymentOptions(BaseModel):
    """Payment options for a Netopia payment."""

    installments: int = 0
    bonus: int = 0


class NetopiaPaymentData(BaseModel):
    """Payment data for a Netopia payment request."""

    options: NetopiaPaymentOptions = Field(default_factory=NetopiaPaymentOptions)
    instrument: dict | None = None
    data: dict = {}


class NetopiaConfigData(BaseModel):
    """Configuration data for a Netopia payment request."""

    email_template: str = Field("default", alias="emailTemplate")
    email_subject: str = Field("", alias="emailSubject")
    cancel_url: str = Field("", alias="cancelUrl")
    notify_url: str = Field("", alias="notifyUrl")
    redirect_url: str = Field("", alias="redirectUrl")
    language: str = "ro"

    model_config = {"populate_by_name": True}


class NetopiaStartPaymentRequest(BaseModel):
    """Full Netopia start payment request."""

    config: NetopiaConfigData = Field(default_factory=NetopiaConfigData)
    payment: NetopiaPaymentData = Field(default_factory=NetopiaPaymentData)
    order: NetopiaOrderData = Field(default_factory=NetopiaOrderData)


# ── Response models ──


class NetopiaPaymentResponse(BaseModel):
    """Netopia payment start response."""

    status: int | None = None
    code: str = ""
    message: str = ""
    payment: dict = {}
    error: dict = {}

    model_config = {"populate_by_name": True}


class NetopiaIPNResult(BaseModel):
    """Normalized result of Netopia IPN processing."""

    order_id: str = ""
    status: str = ""  # confirmed, paid_pending, cancelled, credit
    amount: Decimal = Decimal("0")
    currency: str = "RON"
    original_payload: dict = {}

    model_config = {"populate_by_name": True}
