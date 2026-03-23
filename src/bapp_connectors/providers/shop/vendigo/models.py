"""
Pydantic models for Vendigo API request/response payloads.

These model the raw Vendigo API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

# ── Response models ──


class VendigoPaymentOption(BaseModel):
    """Payment option from a Vendigo order."""

    id: int | None = None
    name: str = ""


class VendigoOrderProduct(BaseModel):
    """Product line item from a Vendigo order."""

    sku: str = ""
    name: str = ""
    price: str = ""
    quantity: int = 1


class VendigoOrder(BaseModel):
    """Order from Vendigo API."""

    id: int
    status: str = ""
    date_created: str = ""
    client_first_name: str = ""
    client_last_name: str = ""
    email: str = ""
    phone: str = ""
    delivery_address: str = ""
    delivery_cost: str = "0"
    company: str = ""
    cui: str = ""
    products: list[VendigoOrderProduct] = []
    payment_option: VendigoPaymentOption | None = None

    model_config = {"populate_by_name": True}


class VendigoProduct(BaseModel):
    """Product from Vendigo API."""

    id: int | None = None
    external_id: str = ""
    name: str = ""
    sku: str = ""
    price: Decimal = Decimal("0")
    stock: int = 0

    model_config = {"populate_by_name": True}


# ── Request models ──


class VendigoSetStatusRequest(BaseModel):
    """Payload for setting order status."""

    status: str
    ids: list[int | str]
