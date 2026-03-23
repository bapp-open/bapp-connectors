"""
Pydantic models for eMAG API request/response payloads.

These model the raw eMAG API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Request models ──


class EmagProductUpdateFields(BaseModel):
    """Fields for updating a product offer on eMAG."""

    id: int | None = None
    sku: str = ""
    sale_price: Decimal | None = None
    min_sale_price: Decimal | None = None
    max_sale_price: Decimal | None = None
    recommended_price: Decimal | None = None
    stock: list[dict] | None = None
    handling_time: dict | None = None
    name: str | None = None
    status: int | None = None
    genius: bool | None = None

    model_config = {"populate_by_name": True}


# ── Response models ──


class EmagOrderItem(BaseModel):
    """Line item from an eMAG order."""

    id: int | None = None
    product_id: int | None = None
    part_number: str = Field("", alias="part_number")
    part_number_key: str | None = Field(None, alias="part_number_key")
    product_name: str = ""
    quantity: int = 1
    sale_price: Decimal = Decimal("0")
    original_price: Decimal | None = None
    status: int = 0
    currency: str = "RON"
    vat: Decimal | None = None
    commission: Decimal | None = None

    model_config = {"populate_by_name": True}


class EmagOrder(BaseModel):
    """Order from eMAG API."""

    id: int
    order_id: int | None = None
    status: int = 0
    payment_mode: str = ""
    payment_mode_id: int | None = None
    payment_status: int = 0
    customer: dict | None = None
    products: list[EmagOrderItem] = []
    date: str | None = None
    cashed_co: Decimal | None = None
    cashed_cod: Decimal | None = None
    shipping_tax: Decimal | None = None
    is_complete: int = 0
    vendor_name: str = ""
    details: dict | None = None
    delivery_address: dict | None = None
    billing_address: dict | None = None
    maximum_date_for_shipment: str | None = None
    finalization_date: str | None = None
    attachments: list[dict] = []

    model_config = {"populate_by_name": True}


class EmagProduct(BaseModel):
    """Product offer from eMAG API."""

    id: int | None = None
    part_number: str = ""
    part_number_key: str | None = None
    name: str = ""
    brand: str = ""
    category_id: int | None = None
    sale_price: Decimal = Decimal("0")
    min_sale_price: Decimal | None = None
    max_sale_price: Decimal | None = None
    recommended_price: Decimal | None = None
    currency_code: str = "RON"
    stock: list[dict] = []
    handling_time: dict | None = None
    status: int = 0
    genius: bool = False
    buy_button_rank: int | None = None
    images: list[dict] = []
    characteristics: list[dict] = []
    description: str = ""
    ean: list[str] = []
    vat_id: int | None = None

    model_config = {"populate_by_name": True}

    @property
    def total_stock(self) -> int:
        """Sum stock across all warehouses."""
        total = 0
        for entry in self.stock:
            val = entry.get("value", 0)
            if isinstance(val, (int, float)):
                total += int(val)
        return total


class EmagApiResponse(BaseModel):
    """Standard eMAG API response wrapper."""

    is_error: bool = Field(False, alias="isError")
    messages: list[str] = []
    results: list[dict] = []
    current_page: int = Field(0, alias="currentPage")
    no_of_pages: int = Field(0, alias="noOfPages")
    no_of_items: int = Field(0, alias="noOfItems")

    model_config = {"populate_by_name": True}
