"""
Pydantic models for Facebook/Meta Commerce feed items.
"""

from __future__ import annotations

from pydantic import BaseModel


class FacebookFeedItem(BaseModel):
    """A single product item in a Facebook Commerce feed."""

    id: str
    title: str
    description: str
    availability: str  # "in stock" | "out of stock" | "preorder"
    condition: str  # "new" | "refurbished" | "used"
    price: str  # "99.99 RON"
    link: str
    image_link: str
    brand: str = ""
    gtin: str = ""
    mpn: str = ""
    product_type: str = ""
    additional_image_link: str = ""
    # Apparel fields
    gender: str = ""
    age_group: str = ""
    color: str = ""
    size: str = ""
