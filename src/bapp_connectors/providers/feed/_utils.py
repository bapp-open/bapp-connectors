"""
Shared utilities for feed providers.

Internal module — not part of the public API.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decimal import Decimal

    from bapp_connectors.core.dto.product import Product

# ── Brand extraction ──

_BRAND_ATTR_NAMES = frozenset({
    "brand", "marca", "manufacturer", "producator",
    "producător", "brand name", "marque", "fabricant",
})


def extract_brand(product: Product, fallback: str = "") -> str:
    """Extract brand/manufacturer from product attributes.

    Tries common attribute names (brand, manufacturer, marca, etc.)
    and falls back to the provided default.
    """
    for attr in product.attributes:
        if attr.attribute_name.lower().strip() in _BRAND_ATTR_NAMES:
            if attr.values:
                return attr.values[0]
    return product.extra.get("brand", "") or fallback


# ── URL building ──


def build_product_url(template: str, product: Product, base_url: str) -> str:
    """Resolve a product URL template.

    Supports placeholders: {base_url}, {product_id}, {sku}
    """
    url = template.replace("{base_url}", base_url.rstrip("/"))
    url = url.replace("{product_id}", str(product.product_id))
    url = url.replace("{sku}", product.sku or product.product_id)
    return url


# ── HTML stripping ──


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(text: str) -> str:
    """Strip HTML tags from text, returning plain text."""
    if not text:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(text)
    return stripper.get_text().strip()


# ── Price formatting ──


def format_price(price: Decimal | None, currency: str) -> str:
    """Format price as 'AMOUNT CURRENCY' (e.g., '99.99 RON').

    Returns empty string if price is None.
    """
    if price is None:
        return ""
    return f"{price:.2f} {currency.upper()}"


def format_price_plain(price: Decimal | None) -> str:
    """Format price as plain decimal string (e.g., '99.99').

    Returns empty string if price is None.
    """
    if price is None:
        return ""
    return f"{price:.2f}"


# ── Availability ──


def resolve_availability(product: Product, default: str = "in stock") -> str:
    """Determine availability based on stock and active status.

    Returns one of: 'in stock', 'out of stock'.
    """
    if not product.active:
        return "out of stock"
    if product.stock is not None and product.stock <= 0:
        return "out of stock"
    return default


# ── Variant expansion ──


def expand_variants(product: Product, include_variants: bool = True) -> list[dict]:
    """Expand a product into feed items, one per variant if enabled.

    Each returned dict has keys that feed mappers can use:
    - product: the original Product
    - variant: the ProductVariant (or None for parent)
    - item_id: unique ID for this feed item
    - sku: effective SKU
    - barcode: effective barcode/GTIN
    - name: effective name
    - price: effective price
    - stock: effective stock
    - image_url: effective image URL
    """
    base_image = product.photos[0].url if product.photos else ""

    if include_variants and product.variants:
        items = []
        for variant in product.variants:
            if not variant.active:
                continue
            items.append({
                "product": product,
                "variant": variant,
                "item_id": f"{product.product_id}-{variant.variant_id}",
                "sku": variant.sku or product.sku,
                "barcode": variant.barcode or product.barcode,
                "name": variant.name or product.name,
                "price": variant.price if variant.price is not None else product.price,
                "stock": variant.stock if variant.stock is not None else product.stock,
                "image_url": variant.image_url or base_image,
            })
        return items

    return [{
        "product": product,
        "variant": None,
        "item_id": str(product.product_id),
        "sku": product.sku,
        "barcode": product.barcode,
        "name": product.name,
        "price": product.price,
        "stock": product.stock,
        "image_url": base_image,
    }]


# ── Text utilities ──


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len characters."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into single spaces."""
    return _WHITESPACE_RE.sub(" ", text).strip()
