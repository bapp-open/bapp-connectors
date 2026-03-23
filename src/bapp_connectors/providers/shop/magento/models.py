"""Pydantic models for Magento 2 API payloads."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class MagentoCustomAttribute(BaseModel):
    attribute_code: str = ""
    value: str | list | None = None


class MagentoMediaEntry(BaseModel):
    id: int | None = None
    media_type: str = "image"
    label: str = ""
    position: int = 0
    disabled: bool = False
    file: str = ""


class MagentoExtensionAttributes(BaseModel):
    stock_item: dict | None = None
    category_links: list[dict] | None = None


class MagentoProduct(BaseModel):
    id: int | None = None
    sku: str = ""
    name: str = ""
    price: Decimal | None = None
    status: int = 1  # 1=enabled, 2=disabled
    visibility: int = 4  # 4=catalog+search
    type_id: str = "simple"
    weight: Decimal | None = None
    attribute_set_id: int = 4  # Default attribute set
    custom_attributes: list[MagentoCustomAttribute] = []
    media_gallery_entries: list[MagentoMediaEntry] = []
    extension_attributes: MagentoExtensionAttributes | None = None


class MagentoCategory(BaseModel):
    id: int | None = None
    parent_id: int = 0
    name: str = ""
    is_active: bool = True
    level: int = 0
    children_data: list[dict] = []


class MagentoOrderItem(BaseModel):
    item_id: int = 0
    sku: str = ""
    name: str = ""
    qty_ordered: Decimal = Decimal("0")
    price: Decimal = Decimal("0")
    price_incl_tax: Decimal = Decimal("0")
    tax_percent: Decimal = Decimal("0")


class MagentoOrder(BaseModel):
    entity_id: int = 0
    increment_id: str = ""
    status: str = ""
    state: str = ""
    grand_total: Decimal = Decimal("0")
    order_currency_code: str = ""
    created_at: str = ""
    updated_at: str = ""
    items: list[MagentoOrderItem] = []
    billing_address: dict | None = None
    extension_attributes: dict | None = None


class MagentoSearchResult(BaseModel):
    """Wrapper for Magento search/list responses."""
    items: list[dict] = []
    search_criteria: dict = {}
    total_count: int = 0
