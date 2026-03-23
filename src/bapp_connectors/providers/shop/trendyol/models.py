"""
Pydantic models for Trendyol API request/response payloads.

These model the raw Trendyol API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Request models ──


class TrendyolProductPriceInventoryUpdate(BaseModel):
    """Payload for batch price/inventory update."""

    barcode: str
    sale_price: Decimal | None = Field(None, alias="salePrice")
    list_price: Decimal | None = Field(None, alias="listPrice")
    quantity: int | None = None

    model_config = {"populate_by_name": True}


class TrendyolProductUpdate(BaseModel):
    """Payload for batch product update (includes name)."""

    barcode: str
    title: str | None = None
    sale_price: Decimal | None = Field(None, alias="salePrice")
    list_price: Decimal | None = Field(None, alias="listPrice")
    quantity: int | None = None

    model_config = {"populate_by_name": True}


# ── Response models ──


class TrendyolAddress(BaseModel):
    """Address from Trendyol order."""

    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")
    company: str | None = None
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    district: str | None = None
    county_name: str | None = Field(None, alias="countyName")
    postal_code: str | None = Field(None, alias="postalCode")
    country_code: str | None = Field(None, alias="countryCode")
    full_address: str | None = Field(None, alias="fullAddress")
    phone: str | None = None
    tax_number: str | None = Field(None, alias="taxNumber")
    address_lines: dict | None = Field(None, alias="addressLines")

    model_config = {"populate_by_name": True}


class TrendyolOrderLine(BaseModel):
    """Line item from a Trendyol order."""

    product_name: str = Field(alias="productName")
    stock_code: str = Field(alias="stockCode")
    quantity: int = 1
    line_unit_price: Decimal = Field(alias="lineUnitPrice")
    merchant_id: int | None = Field(None, alias="merchantId")
    product_size: str | None = Field(None, alias="productSize")
    product_color: str | None = Field(None, alias="productColor")
    product_main_id: str | None = Field(None, alias="productMainId")
    barcode: str | None = None

    model_config = {"populate_by_name": True}


class TrendyolOrder(BaseModel):
    """Order from Trendyol API."""

    id: int | None = None
    order_number: str = Field(alias="orderNumber")
    order_date: int = Field(alias="orderDate")  # timestamp in ms
    status: str = ""
    currency_code: str = Field("TRY", alias="currencyCode")
    customer_email: str | None = Field(None, alias="customerEmail")
    invoice_address: TrendyolAddress | None = Field(None, alias="invoiceAddress")
    shipment_address: TrendyolAddress | None = Field(None, alias="shipmentAddress")
    lines: list[TrendyolOrderLine] = []
    shipment_package_id: int | None = Field(None, alias="shipmentPackageId")
    cargo_tracking_number: str | None = Field(None, alias="cargoTrackingNumber")

    model_config = {"populate_by_name": True}


class TrendyolProduct(BaseModel):
    """Product from Trendyol API."""

    barcode: str = ""
    title: str = ""
    product_main_id: str = Field("", alias="productMainId")
    sale_price: Decimal = Field(Decimal("0"), alias="salePrice")
    list_price: Decimal = Field(Decimal("0"), alias="listPrice")
    quantity: int = 0
    archived: bool = False
    approved: bool = False

    model_config = {"populate_by_name": True}


class TrendyolPaginatedResponse(BaseModel):
    """Generic paginated response from Trendyol."""

    content: list[dict] = []
    total_elements: int = Field(0, alias="totalElements")
    total_pages: int = Field(0, alias="totalPages")
    page: int = 0
    size: int = 0

    model_config = {"populate_by_name": True}
