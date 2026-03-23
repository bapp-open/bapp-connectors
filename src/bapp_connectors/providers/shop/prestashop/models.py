"""
Pydantic models for PrestaShop API request/response payloads.

These model the raw PrestaShop Webservice API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.

Reference: https://devdocs.prestashop-project.org/8/webservice/
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Response models ──


class PrestaShopAddress(BaseModel):
    """Address from PrestaShop API."""

    id: str = ""
    id_customer: str = ""
    id_country: str = ""
    id_state: str = ""
    alias: str = ""
    company: str = ""
    lastname: str = ""
    firstname: str = ""
    vat_number: str = ""
    address1: str = ""
    address2: str = ""
    postcode: str = ""
    city: str = ""
    phone: str = ""
    phone_mobile: str = ""
    dni: str = ""

    model_config = {"populate_by_name": True}


class PrestaShopCustomer(BaseModel):
    """Customer from PrestaShop API."""

    id: str = ""
    firstname: str = ""
    lastname: str = ""
    email: str = ""
    company: str = ""

    model_config = {"populate_by_name": True}


class PrestaShopCountry(BaseModel):
    """Country from PrestaShop API."""

    id: str = ""
    iso_code: str = ""
    name: str = ""

    model_config = {"populate_by_name": True}


class PrestaShopState(BaseModel):
    """State/region from PrestaShop API."""

    id: str = ""
    name: str = ""
    iso_code: str = ""

    model_config = {"populate_by_name": True}


class PrestaShopOrderRow(BaseModel):
    """Order line item from PrestaShop API."""

    id: str = ""
    product_id: str = ""
    product_reference: str = ""
    product_name: str = ""
    product_quantity: int = 1
    unit_price_tax_incl: Decimal = Decimal("0")
    unit_price_tax_excl: Decimal = Decimal("0")

    model_config = {"populate_by_name": True}


class PrestaShopOrder(BaseModel):
    """Order from PrestaShop API."""

    id: str = ""
    reference: str = ""
    id_customer: str = ""
    id_address_delivery: str = ""
    id_address_invoice: str = ""
    current_state: str = ""
    module: str = ""  # payment module
    date_add: str = ""
    date_upd: str = ""
    total_paid_tax_incl: Decimal = Decimal("0")
    total_shipping_tax_incl: Decimal = Decimal("0")
    associations: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class PrestaShopProduct(BaseModel):
    """Product from PrestaShop API."""

    id: str = ""
    reference: str = ""
    name: dict | str = ""  # Can be multilingual dict or string
    price: Decimal = Decimal("0")
    quantity: int = 0
    id_category_default: str = ""
    id_default_image: str = ""
    active: str = "1"
    ean13: str = ""
    stock_quantity: int | None = None

    model_config = {"populate_by_name": True}


class PrestaShopCategory(BaseModel):
    """Category from PrestaShop API."""

    id: str = ""
    id_parent: str = ""
    name: dict | str = ""  # Can be multilingual dict or string
    active: str = "1"

    model_config = {"populate_by_name": True}
