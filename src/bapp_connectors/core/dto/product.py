"""
Normalized DTOs for products.
"""

from __future__ import annotations

from decimal import Decimal

from .base import BaseDTO


class ProductCategory(BaseDTO):
    """Normalized product category."""

    category_id: str
    name: str = ""
    parent_id: str | None = None
    extra: dict = {}


class ProductPhoto(BaseDTO):
    """Normalized product photo."""

    url: str
    position: int = 0
    alt_text: str = ""


class ProductVariant(BaseDTO):
    """Normalized product variant (size, color, etc.)."""

    variant_id: str
    sku: str | None = None
    barcode: str | None = None
    name: str = ""
    price: Decimal | None = None
    stock: int | None = None
    attributes: dict = {}
    extra: dict = {}


class Product(BaseDTO):
    """Normalized product."""

    product_id: str
    sku: str | None = None
    barcode: str | None = None
    name: str = ""
    description: str = ""
    price: Decimal | None = None
    currency: str = ""
    stock: int | None = None
    active: bool = True
    categories: list[str] = []
    photos: list[ProductPhoto] = []
    variants: list[ProductVariant] = []
    extra: dict = {}


class ProductUpdate(BaseDTO):
    """Payload for updating a product on the provider side."""

    product_id: str
    sku: str | None = None
    barcode: str | None = None
    name: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    stock: int | None = None
    active: bool | None = None
    extra: dict = {}
