"""
Pydantic models for raw Google Ads REST API (v17) payloads.

These model GAQL search result rows as returned by ``googleAds:search`` —
they are NOT normalized DTOs. Field names match the REST camelCase wire
format; int64 values arrive as JSON strings.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GoogleAdsCustomer(BaseModel):
    """``customer`` resource fields selected in GAQL queries."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    id: str | int = ""
    descriptiveName: str = ""
    currencyCode: str = ""


class GoogleAdsCampaign(BaseModel):
    """``campaign`` resource fields selected in GAQL queries."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    id: str | int = ""
    name: str = ""
    status: str = ""
    advertisingChannelType: str = ""
    startDate: str = ""
    endDate: str = ""


class GoogleAdsCampaignBudget(BaseModel):
    """``campaign_budget`` resource fields selected in GAQL queries."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    amountMicros: str | int | None = None


class GoogleAdsAdGroup(BaseModel):
    """``ad_group`` resource fields selected in GAQL queries."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    id: str | int = ""
    name: str = ""
    status: str = ""
    cpcBidMicros: str | int | None = None


class GoogleAdsAd(BaseModel):
    """The nested ``ad`` object inside an ``ad_group_ad``."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    id: str | int = ""
    name: str = ""
    finalUrls: list[str] = []
    responsiveSearchAd: dict = {}


class GoogleAdsAdGroupAd(BaseModel):
    """``ad_group_ad`` resource fields selected in GAQL queries."""

    model_config = ConfigDict(extra="allow")

    resourceName: str = ""
    status: str = ""
    ad: GoogleAdsAd = GoogleAdsAd()


class GoogleAdsMetrics(BaseModel):
    """``metrics`` fields selected in insight queries (money fields are micros)."""

    model_config = ConfigDict(extra="allow")

    impressions: str | int | None = None
    clicks: str | int | None = None
    costMicros: str | int | None = None
    ctr: float | str | None = None
    averageCpc: str | int | float | None = None
    averageCpm: str | int | float | None = None
    conversions: float | str | None = None
    conversionsValue: float | str | None = None
    videoViews: str | int | None = None


class GoogleAdsCampaignRow(BaseModel):
    """One googleAds:search row from a ``FROM campaign`` query."""

    model_config = ConfigDict(extra="allow")

    campaign: GoogleAdsCampaign = GoogleAdsCampaign()
    campaignBudget: GoogleAdsCampaignBudget = GoogleAdsCampaignBudget()
    customer: GoogleAdsCustomer = GoogleAdsCustomer()


class GoogleAdsAdGroupRow(BaseModel):
    """One googleAds:search row from a ``FROM ad_group`` query."""

    model_config = ConfigDict(extra="allow")

    adGroup: GoogleAdsAdGroup = GoogleAdsAdGroup()
    campaign: GoogleAdsCampaign = GoogleAdsCampaign()


class GoogleAdsAdGroupAdRow(BaseModel):
    """One googleAds:search row from a ``FROM ad_group_ad`` query."""

    model_config = ConfigDict(extra="allow")

    adGroupAd: GoogleAdsAdGroupAd = GoogleAdsAdGroupAd()
    adGroup: GoogleAdsAdGroup = GoogleAdsAdGroup()
    campaign: GoogleAdsCampaign = GoogleAdsCampaign()


class GoogleAdsMetricsRow(BaseModel):
    """One googleAds:search row from an insights (metrics) query."""

    model_config = ConfigDict(extra="allow")

    metrics: GoogleAdsMetrics = GoogleAdsMetrics()
    segments: dict = {}
    customer: GoogleAdsCustomer = GoogleAdsCustomer()
    campaign: GoogleAdsCampaign = GoogleAdsCampaign()
    adGroup: GoogleAdsAdGroup = GoogleAdsAdGroup()
    adGroupAd: GoogleAdsAdGroupAd = GoogleAdsAdGroupAd()
