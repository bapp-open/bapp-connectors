"""
Pydantic models for Okazii API request/response payloads.

These model the raw Okazii API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

# ── Response models ──


class OkaziiPrice(BaseModel):
    """Price object from Okazii API."""

    amount: Decimal = Decimal("0")
    currency: str = "RON"


class OkaziiBid(BaseModel):
    """Bid (line item) from an Okazii order."""

    auction_unique_id: str = Field("", alias="auctionUniqueId")
    item_price: OkaziiPrice = Field(default_factory=OkaziiPrice, alias="itemPrice")
    amount: int = 1
    status: str = ""
    payment_method: str = Field("", alias="paymentMethod")

    model_config = {"populate_by_name": True}


class OkaziiAddress(BaseModel):
    """Address from Okazii API."""

    street: str = ""
    street_nr: str = Field("", alias="streetNr")
    city: str = ""
    county: str = ""
    zipcode: str = ""
    country: str = "RO"

    model_config = {"populate_by_name": True}


class OkaziiBillingInfo(BaseModel):
    """Billing info from Okazii API."""

    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")
    company: str = ""
    cui: str = ""
    address: str = ""
    street: str = ""
    street_nr: str = Field("", alias="streetNr")
    city: str = ""
    county: str = ""
    zipcode: str = ""

    model_config = {"populate_by_name": True}


class OkaziiBuyerContact(BaseModel):
    """Buyer contact from Okazii API."""

    first_name: str = Field("", alias="firstName")
    last_name: str = Field("", alias="lastName")
    email: str = ""
    phone: str = ""

    model_config = {"populate_by_name": True}


class OkaziiOrder(BaseModel):
    """Order from Okazii API."""

    id: int
    created_at: str = Field("", alias="createdAt")
    bids: list[OkaziiBid] = []
    delivery_address: OkaziiAddress = Field(default_factory=OkaziiAddress, alias="deliveryAddress")
    delivery_price: OkaziiPrice | None = Field(None, alias="deliveryPrice")
    billing_info: OkaziiBillingInfo | None = Field(None, alias="billingInfo")
    buyer_contact: OkaziiBuyerContact = Field(default_factory=OkaziiBuyerContact, alias="buyerContact")

    model_config = {"populate_by_name": True}


class OkaziiHydraResponse(BaseModel):
    """Hydra-style paginated response from Okazii API."""

    members: list[dict] = Field([], alias="hydra:member")
    total_items: int = Field(0, alias="hydra:totalItems")

    model_config = {"populate_by_name": True}
