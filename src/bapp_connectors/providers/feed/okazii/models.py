"""
Pydantic models for Okazii.ro feed items.

Mirrors the <AUCTION> XML structure documented at:
https://ajutor.okazii.ro/magazine-okazii-ro/import-produse.html
"""

from __future__ import annotations

from pydantic import BaseModel


class OkaziiCourier(BaseModel):
    """A courier option within the DELIVERY section."""

    name: str = ""
    area: str = "in romania"
    price: str = ""
    currency: str = "RON"


class OkaziiStock(BaseModel):
    """A stock/variant entry within the STOCKS section."""

    amount: int = 0
    size: str = ""  # MARIME
    color: str = ""  # CULOARE
    gtin: str = ""


class OkaziiFeedItem(BaseModel):
    """A single product (AUCTION) in an Okazii feed."""

    # Required
    unique_id: str
    title: str
    category: str
    description: str
    price: str  # plain decimal
    currency: str = "RON"
    amount: int = 0  # total stock quantity

    # Optional product info
    discount_price: str = ""
    brand: str = ""
    sku: str = ""
    gtin: str = ""
    in_stock: int = 1  # 0=out of stock, 1=in stock

    # Condition & policies
    state: int = 1  # 1=new, 2=used
    invoice: int = 1  # 1=yes, 2=no
    warranty: int = 1  # 1=yes, 2=no

    # Images
    photos: list[str] = []

    # Payment
    payment_personal: int = 0  # cash on pickup
    payment_ramburs: int = 1  # cash on delivery
    payment_avans: int = 1  # bank transfer

    # Delivery
    delivery_personal: int = 0  # pickup available
    delivery_time: int = 3  # days
    couriers: list[OkaziiCourier] = []

    # Return
    return_accept: int = 1  # 1=yes, 0=no
    return_days: int = 14
    return_method: int = 2  # 1=sender pays, 2=seller pays
    return_cost: int = 0  # 0=free, 1=paid

    # Attributes (non-variant)
    attributes: dict[str, str] = {}

    # Stock variants
    stocks: list[OkaziiStock] = []
