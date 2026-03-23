"""
Pydantic models for GLS API request/response payloads.

These model the raw GLS API — they are NOT normalized DTOs.
Conversion between these and DTOs happens in mappers.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request models ──


class GLSAddress(BaseModel):
    """Address for GLS parcel."""

    Name: str
    Street: str
    HouseNumber: str = ""
    HouseNumberInfo: str = ""
    City: str
    ZipCode: str
    CountryIsoCode: str = "RO"
    ContactName: str = ""
    ContactPhone: str = ""
    ContactEmail: str = ""


class GLSParcel(BaseModel):
    """A single parcel in a GLS AWB request."""

    ClientNumber: int
    ClientReference: str = ""
    Count: int = 1
    CODAmount: float | None = None
    CODReference: str | None = None
    CODCurrency: str | None = Field(None, max_length=3)
    Content: str | None = None
    PickupDate: str | None = None
    PickupAddress: GLSAddress
    DeliveryAddress: GLSAddress
    ServiceList: list[dict] | None = None


# ── Response models ──


class GLSErrorInfo(BaseModel):
    """Error from GLS API."""

    ErrorCode: int = 0
    ErrorDescription: str = ""
    ClientReferenceList: list[str] = []
    ParcelIdList: list[int] = []


class GLSParcelInfo(BaseModel):
    """Info about a generated parcel label."""

    ClientReference: str = ""
    ParcelId: int = 0
    ParcelNumber: int = 0


class GLSParcelResponse(BaseModel):
    """Response from GLS PrintLabels."""

    Labels: list[int] | None = None
    PrintLabelsInfoList: list[GLSParcelInfo] = []
    PrintLabelsErrorList: list[GLSErrorInfo] = []


class GLSParcelStatus(BaseModel):
    """A single status event from parcel tracking."""

    DepotCity: str = ""
    DepotNumber: str = ""
    StatusCode: str = ""
    StatusDate: str = ""
    StatusDescription: str = ""
    StatusInfo: str = ""


class GLSParcelStatuses(BaseModel):
    """Response from GLS GetParcelStatuses."""

    ClientReference: str = ""
    DeliveryCountryInfo: str | None = None
    DeliveryZipCode: str = ""
    GetParcelStatusErrors: list[GLSErrorInfo] = []
    ParcelNumber: int = 0
    ParcelStatusList: list[GLSParcelStatus] = []
    POD: list[int] | None = None
    Weight: float | None = None


class GLSParcelPrintResponse(BaseModel):
    """Response from GLS GetParcelList."""

    GetParcelListErrors: list[GLSErrorInfo] = []
    PrintDataInfoList: list[dict] = []
