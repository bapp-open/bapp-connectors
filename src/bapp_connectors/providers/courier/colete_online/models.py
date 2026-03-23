"""
Pydantic models for Colete Online API request/response payloads.

These model the raw Colete Online API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Request models ──


class COContact(BaseModel):
    """Contact details for sender/recipient."""

    name: str
    phone: str
    phone2: str = ""
    email: str = ""
    company: str = ""


class COAddress(BaseModel):
    """Address for sender/recipient."""

    countryCode: str = "RO"
    postalCode: str = ""
    city: str = ""
    county: str = ""
    street: str = ""
    number: str = ""
    block: str = ""
    entrance: str = ""
    intercom: str = ""
    floor: str = ""
    apartment: str = ""


class COShippingPoint(BaseModel):
    """Shipping point reference (for point-to-point delivery)."""

    id: int
    countryCode: str = "RO"


class COParty(BaseModel):
    """Sender or recipient in an order."""

    contact: COContact
    address: COAddress | None = None
    shippingPoint: COShippingPoint | None = None


class COPackageItem(BaseModel):
    """A single package in an order."""

    weight: float = 1.0
    width: float = 0.0
    height: float = 0.0
    length: float = 0.0


class COPackages(BaseModel):
    """Package details for an order."""

    type: int = 2  # 2 = parcel
    content: str = ""
    list: list[COPackageItem] = []


class COService(BaseModel):
    """Service selection for an order."""

    selectionType: str = "bestPrice"
    serviceIds: list[int] = []
    activationId: str = ""
    specific: dict | None = None


class COExtraOption(BaseModel):
    """Extra option for an order."""

    id: int
    override: bool = True
    value: str | float | None = None


class COOrder(BaseModel):
    """Complete order request payload."""

    sender: COParty
    recipient: COParty
    packages: COPackages
    service: COService
    extraOptions: list[COExtraOption] = []


# ── Response models ──


class COOrderResponse(BaseModel):
    """Response from order creation."""

    uniqueId: str = Field("", alias="uniqueId")
    courierName: str = ""
    trackingNumber: str = ""
    price: float = 0.0
    status: str = ""

    model_config = {"populate_by_name": True}


class COStatusEvent(BaseModel):
    """A single status event from order tracking."""

    status: str = ""
    statusDescription: str = ""
    date: str = ""
    location: str = ""
    county: str = ""

    model_config = {"populate_by_name": True}


class COPriceResult(BaseModel):
    """Price estimate result for a service."""

    serviceId: int = 0
    serviceName: str = ""
    price: float = 0.0
    currency: str = "RON"
    deliveryDays: int = 0

    model_config = {"populate_by_name": True}
