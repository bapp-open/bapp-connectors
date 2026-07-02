"""
Pydantic models for raw LinkedIn Marketing API payloads.

These model the raw REST API — they are NOT normalized DTOs. Money amounts
are ``{"amount": "10.5", "currencyCode": "USD"}`` records with the amount in
currency units as a string; runSchedule timestamps are epoch milliseconds.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LinkedInMoney(BaseModel):
    """Raw money amount record."""

    model_config = ConfigDict(extra="allow")

    amount: str = ""
    currencyCode: str = ""


class LinkedInRunSchedule(BaseModel):
    """Raw run schedule record (epoch milliseconds)."""

    model_config = ConfigDict(extra="allow")

    start: int | None = None
    end: int | None = None


class LinkedInCampaignGroup(BaseModel):
    """Raw adCampaignGroups entity (maps to the framework AdCampaign)."""

    model_config = ConfigDict(extra="allow")

    id: int | str = ""
    account: str = ""
    name: str = ""
    status: str = ""
    totalBudget: dict | None = None
    runSchedule: dict = {}


class LinkedInCampaign(BaseModel):
    """Raw adCampaigns entity (maps to the framework AdGroup)."""

    model_config = ConfigDict(extra="allow")

    id: int | str = ""
    account: str = ""
    campaignGroup: str = ""
    name: str = ""
    status: str = ""
    type: str = ""
    costType: str = ""
    unitCost: dict | None = None
    dailyBudget: dict | None = None
    totalBudget: dict | None = None
    targetingCriteria: dict = {}
    runSchedule: dict = {}


class LinkedInCreative(BaseModel):
    """Raw creatives entity (maps to the framework Ad)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""  # a full URN, e.g. urn:li:sponsoredCreative:123
    campaign: str = ""
    intendedStatus: str = ""
    content: dict = {}


class LinkedInAnalyticsRow(BaseModel):
    """One element from the adAnalytics finder."""

    model_config = ConfigDict(extra="allow")

    impressions: int | None = None
    clicks: int | None = None
    costInLocalCurrency: str | None = None
    externalWebsiteConversions: int | None = None
    dateRange: dict = {}
    pivotValues: list[str] = []
