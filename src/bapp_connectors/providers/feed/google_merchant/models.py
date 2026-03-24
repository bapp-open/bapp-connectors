"""
Pydantic models for Google Merchant feed items.

These are intermediate validated models used between the mapper
and the XML/CSV serializer — not framework DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel


class GoogleFeedItem(BaseModel):
    """A single product item in a Google Merchant feed."""

    id: str
    title: str
    description: str
    link: str
    image_link: str
    price: str  # "99.99 RON"
    availability: str  # "in stock" | "out of stock" | "preorder"
    condition: str  # "new" | "refurbished" | "used"
    brand: str = ""
    gtin: str = ""
    mpn: str = ""
    product_type: str = ""
    additional_image_links: list[str] = []
    sale_price: str = ""
