"""
Pydantic models for CEL.ro API request/response payloads.

These model the raw CEL API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Request models ──


class CelOrderFilter(BaseModel):
    """Filters for fetching orders."""

    date: dict | None = None  # {"minDate": "YYYY-MM-DD HH:MM:SS"}
    order_status: int | None = None


class CelOrdersRequest(BaseModel):
    """Payload for orders/getOrders endpoint."""

    filters: CelOrderFilter = Field(default_factory=CelOrderFilter)
    start: int = 0
    limit: int = 100


# ── Response models ──


class CelLoginResponse(BaseModel):
    """Response from login/actionLogin endpoint."""

    token_status: bool = Field(False, alias="tokenStatus")
    message: str = ""

    model_config = {"populate_by_name": True}


class CelCustomer(BaseModel):
    """Customer from a CEL order."""

    billing_country: str = ""
    shipping_country: str = ""
    shipping_street: str = ""
    firstname: str = ""
    lastname: str = ""
    email: str = ""
    phone: str = ""
    company: str = ""
    vat_number: str = ""

    model_config = {"populate_by_name": True}


class CelOrderProduct(BaseModel):
    """Product line item from a CEL order."""

    sku: str = ""
    name: str = ""
    price: Decimal = Decimal("0")
    quantity: int = 1
    currency: str = "RON"

    model_config = {"populate_by_name": True}


class CelOrder(BaseModel):
    """Order from CEL API."""

    id: int | None = None
    order_id: str = ""
    date: str = ""
    status: int = 1
    payment_mode_id: int = 0
    customer: CelCustomer = Field(default_factory=CelCustomer)
    products: list[CelOrderProduct] = []

    model_config = {"populate_by_name": True}


class CelCategory(BaseModel):
    """Category from CEL API."""

    id: int | None = None
    name: str = ""
    parent_id: int | None = None

    model_config = {"populate_by_name": True}
