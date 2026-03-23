"""
Pydantic models for Gomag API request/response payloads.

These model the raw Gomag API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Response models ──


class GomagOrderProduct(BaseModel):
    """Product line item from a Gomag order."""

    product_id: str = ""
    product_name: str = ""
    model: str = ""
    sku: str = ""
    quantity: int = 1
    price: Decimal = Decimal("0")
    total: Decimal = Decimal("0")

    model_config = {"populate_by_name": True}


class GomagOrder(BaseModel):
    """Order from Gomag API."""

    order_id: str = ""
    date_added: str = ""
    status_name: str = Field("", alias="status_name")
    total: Decimal = Decimal("0")
    currency_code: str = "RON"
    payment_method: str = ""
    firstname: str = ""
    lastname: str = ""
    email: str = ""
    telephone: str = ""
    company: str = ""
    payment_firstname: str = ""
    payment_lastname: str = ""
    payment_company: str = ""
    payment_address_1: str = ""
    payment_address_2: str = ""
    payment_city: str = ""
    payment_zone: str = ""
    payment_postcode: str = ""
    payment_country: str = ""
    shipping_firstname: str = ""
    shipping_lastname: str = ""
    shipping_company: str = ""
    shipping_address_1: str = ""
    shipping_address_2: str = ""
    shipping_city: str = ""
    shipping_zone: str = ""
    shipping_postcode: str = ""
    shipping_country: str = ""
    products: list[GomagOrderProduct] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class GomagProduct(BaseModel):
    """Product from Gomag API."""

    product_id: str = ""
    name: str = ""
    model: str = ""
    sku: str = ""
    price: Decimal = Decimal("0")
    quantity: int = 0
    status: str = "1"  # "1" = enabled
    description: str = ""
    image: str = ""
    category: str = ""

    model_config = {"populate_by_name": True}


class GomagCategory(BaseModel):
    """Category from Gomag API."""

    category_id: str = ""
    name: str = ""
    parent_id: str = ""

    model_config = {"populate_by_name": True}
