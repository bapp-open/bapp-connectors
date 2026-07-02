"""
Pydantic models for parsed Bing Ads API v13 SOAP payloads.

The client parses SOAP XML into plain dicts with the original PascalCase
element names; these models validate/shape those dicts before mapping. They
are NOT normalized DTOs. Dates are the parsed form of Bing's ``Date`` complex
type: ``{"Day": ..., "Month": ..., "Year": ...}``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MicrosoftCampaign(BaseModel):
    """One ``Campaign`` element from GetCampaignsByAccountId."""

    model_config = ConfigDict(extra="allow")

    Id: str | int = ""
    Name: str = ""
    Status: str = ""
    BudgetType: str = ""
    DailyBudget: str | float | None = None
    TimeZone: str = ""
    CampaignType: str = ""


class MicrosoftAdGroup(BaseModel):
    """One ``AdGroup`` element from GetAdGroupsByCampaignId. ``CpcBid`` is the bid Amount."""

    model_config = ConfigDict(extra="allow")

    Id: str | int = ""
    Name: str = ""
    Status: str = ""
    CpcBid: str | float | None = None
    StartDate: dict | None = None
    EndDate: dict | None = None


class MicrosoftAd(BaseModel):
    """One ``Ad`` element from GetAdsByAdGroupId.

    ``Headlines``/``Descriptions`` are the flattened TextAsset texts of a
    responsive search ad; ``Title``/``Text`` cover legacy text ad shapes.
    """

    model_config = ConfigDict(extra="allow")

    Id: str | int = ""
    Type: str = ""
    Status: str = ""
    FinalUrls: list[str] = []
    Headlines: list[str] = []
    Descriptions: list[str] = []
    Title: str = ""
    Text: str = ""
