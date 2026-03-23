"""Pydantic models for Shopify Admin API payloads."""

from __future__ import annotations

from pydantic import BaseModel


class ShopifyVariant(BaseModel):
    id: int | None = None
    product_id: int | None = None
    title: str = ""
    price: str = "0.00"
    sku: str = ""
    barcode: str = ""
    inventory_quantity: int = 0
    option1: str | None = None
    option2: str | None = None
    option3: str | None = None
    weight: float | None = None
    weight_unit: str = "kg"
    taxable: bool = True
    requires_shipping: bool = True


class ShopifyImage(BaseModel):
    id: int | None = None
    src: str = ""
    alt: str = ""
    position: int = 0


class ShopifyProduct(BaseModel):
    id: int | None = None
    title: str = ""
    body_html: str = ""
    vendor: str = ""
    product_type: str = ""
    status: str = "active"  # active, draft, archived
    tags: str = ""
    handle: str = ""
    variants: list[ShopifyVariant] = []
    images: list[ShopifyImage] = []
    options: list[dict] = []


class ShopifyOrder(BaseModel):
    id: int | None = None
    name: str = ""  # display order number like "#1001"
    order_number: int = 0
    financial_status: str = ""
    fulfillment_status: str | None = None
    total_price: str = "0.00"
    currency: str = ""
    created_at: str = ""
    updated_at: str = ""
    line_items: list[dict] = []
    billing_address: dict | None = None
    shipping_address: dict | None = None
    customer: dict | None = None


class ShopifyWebhook(BaseModel):
    id: int | None = None
    topic: str = ""
    address: str = ""
    format: str = "json"
