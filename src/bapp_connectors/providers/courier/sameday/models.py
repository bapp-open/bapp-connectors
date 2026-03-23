"""
Pydantic models for Sameday API request/response payloads.

These model the raw Sameday API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ── Request models ──


class AWBRecipient(BaseModel):
    """Recipient details for AWB generation."""

    name: str
    phone: str
    county: str = ""
    city: str = ""
    address: str = ""
    postal_code: str = Field("", alias="postalCode")
    company: str = ""
    email: str = ""

    model_config = {"populate_by_name": True}


class SamedayParcel(BaseModel):
    """A single parcel in a Sameday AWB request."""

    weight: float = 1.0
    width: float = 0.0
    height: float = 0.0
    length: float = 0.0
    is_last: bool = Field(True, alias="isLast")

    model_config = {"populate_by_name": True}


# ── Response models ──


class SamedayParcelResponse(BaseModel):
    """Response from Sameday AWB generation."""

    awb_number: str = Field("", alias="awbNumber")
    awb_cost: float = Field(0.0, alias="awbCost")
    parcels: list[str] = []

    model_config = {"populate_by_name": True}


class SamedayStatusEvent(BaseModel):
    """A single status event from parcel tracking history."""

    status_id: int = Field(0, alias="statusId")
    status: str = ""
    status_label: str = Field("", alias="statusLabel")
    status_state: str = Field("", alias="statusState")
    county: str = ""
    reason: str = ""
    transit_location: str = Field("", alias="transitLocation")
    created_at: datetime | None = Field(None, alias="createdAt")

    model_config = {"populate_by_name": True}


class SamedayParcelStatus(BaseModel):
    """Response from Sameday parcel status history endpoint."""

    awb_number: str = Field("", alias="awbNumber")
    awb_history: list[SamedayStatusEvent] = Field([], alias="awbHistory")

    model_config = {"populate_by_name": True}


class SamedayPickupPoint(BaseModel):
    """Pickup point from Sameday API."""

    id: int = 0
    alias: str = ""
    county: str = ""
    city: str = ""
    address: str = ""
    default_pickup_point: bool = Field(False, alias="defaultPickupPoint")
    contact_persons: list[dict] = Field([], alias="contactPersons")

    model_config = {"populate_by_name": True}
