"""
Pydantic models for Compari.ro feed items.
"""

from __future__ import annotations

from pydantic import BaseModel


class CompariFeedItem(BaseModel):
    """A single product item in a Compari.ro feed."""

    identifier: str
    name: str
    product_url: str
    price: str  # plain decimal "99.99"
    category: str
    image_url: str
    description: str
    manufacturer: str = ""
    currency: str = "RON"
    ean_code: str = ""
    delivery_time: str = ""
    delivery_cost: str = ""
