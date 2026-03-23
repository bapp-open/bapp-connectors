"""
Pydantic models for WooCommerce API request/response payloads.

These model the raw WooCommerce API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Response models ──


class WooAddress(BaseModel):
    """Billing or shipping address from WooCommerce order."""

    first_name: str = ""
    last_name: str = ""
    company: str = ""
    address_1: str = ""
    address_2: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""
    country: str = ""
    email: str = ""
    phone: str = ""

    model_config = {"populate_by_name": True}


class WooOrderLineItem(BaseModel):
    """Line item from a WooCommerce order."""

    id: int = 0
    name: str = ""
    product_id: int = 0
    variation_id: int = 0
    quantity: int = 1
    sku: str = ""
    price: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")

    model_config = {"populate_by_name": True}


class WooOrder(BaseModel):
    """Order from WooCommerce API."""

    id: int = 0
    number: str = ""
    status: str = ""
    currency: str = "RON"
    date_created: str = ""
    date_modified: str = ""
    total: Decimal = Decimal("0")
    payment_method: str = ""
    payment_method_title: str = ""
    customer_note: str = ""
    billing: WooAddress | None = None
    shipping: WooAddress | None = None
    line_items: list[WooOrderLineItem] = Field(default_factory=list)
    shipping_lines: list[dict] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WooProduct(BaseModel):
    """Product from WooCommerce API."""

    id: int = 0
    name: str = ""
    sku: str = ""
    slug: str = ""
    status: str = "publish"
    price: Decimal | None = None
    regular_price: Decimal | None = None
    sale_price: Decimal | None = None
    stock_quantity: int | None = None
    stock_status: str = ""
    manage_stock: bool = False
    description: str = ""
    short_description: str = ""
    categories: list[dict] = Field(default_factory=list)
    images: list[dict] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class WooWebhook(BaseModel):
    """Webhook registration from WooCommerce API."""

    id: int = 0
    name: str = ""
    status: str = "active"
    topic: str = ""
    delivery_url: str = ""
    secret: str = ""

    model_config = {"populate_by_name": True}
