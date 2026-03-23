"""
Normalized DTOs for products, attributes, variants, and related products.
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


# ── Attributes ──


class AttributeValue(BaseDTO):
    """A single value within an attribute definition (e.g., 'Red' for Color)."""

    value_id: str = ""
    name: str = ""
    slug: str = ""
    extra: dict = {}


class AttributeDefinition(BaseDTO):
    """A product attribute definition (e.g., Color with values [Red, Blue, Green])."""

    attribute_id: str
    name: str = ""
    slug: str = ""
    attribute_type: str = "select"  # select, text, bool, etc.
    values: list[AttributeValue] = []
    extra: dict = {}


class ProductAttribute(BaseDTO):
    """An attribute assignment on a product (e.g., Color=[Red, Blue] on product X)."""

    attribute_id: str = ""
    attribute_name: str = ""
    values: list[str] = []  # selected values (e.g., ["Red", "Blue"])
    visible: bool = True
    used_for_variants: bool = False  # WooCommerce "variation", PrestaShop option vs feature
    position: int = 0
    extra: dict = {}


# ── Related Products ──


class RelatedProductLink(BaseDTO):
    """A relationship link between two products."""

    product_id: str
    link_type: str = "related"  # "related", "upsell", "crosssell"
    position: int = 0
    extra: dict = {}


# ── Variants ──


class ProductVariant(BaseDTO):
    """Normalized product variant (size, color, etc.)."""

    variant_id: str
    sku: str | None = None
    barcode: str | None = None
    name: str = ""
    price: Decimal | None = None
    stock: int | None = None
    attributes: dict = {}  # e.g., {"Color": "Red", "Size": "L"}
    image_url: str = ""
    weight: Decimal | None = None
    active: bool = True
    extra: dict = {}


# ── Product ──


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
    attributes: list[ProductAttribute] = []
    variants: list[ProductVariant] = []
    related: list[RelatedProductLink] = []
    extra: dict = {}


class ProductUpdate(BaseDTO):
    """Payload for updating a product on the provider side.

    All fields except product_id are optional — set only the fields you want to change.
    """

    product_id: str
    sku: str | None = None
    barcode: str | None = None
    name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    stock: int | None = None
    active: bool | None = None
    categories: list[str] | None = None
    photos: list[ProductPhoto] | None = None
    attributes: list[ProductAttribute] | None = None
    variants: list[ProductVariant] | None = None
    related: list[RelatedProductLink] | None = None
    extra: dict = {}
