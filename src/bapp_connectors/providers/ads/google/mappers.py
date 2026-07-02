"""
Google Ads <-> DTO mappers.

Converts between raw Google Ads REST API (v17) GAQL rows and normalized
framework DTOs. Money is micros (int64 serialized as string): 1 currency
unit = 1,000,000 micros, always in the account currency.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    AdObjective,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.ads.google.models import (
    GoogleAdsAdGroupAdRow,
    GoogleAdsAdGroupRow,
    GoogleAdsCampaignRow,
    GoogleAdsMetricsRow,
)

MICROS_PER_UNIT = Decimal(1_000_000)

# ── Money ──


def micros_to_decimal(value: str | int | float | None) -> Decimal | None:
    """Convert a micros amount (int64 as string/number) to a Decimal currency amount."""
    if value is None or value == "":
        return None
    return Decimal(str(value)) / MICROS_PER_UNIT


def decimal_to_micros(value: Decimal | int | float | str) -> int:
    """Convert a Decimal currency amount to Google micros (int)."""
    return int((Decimal(str(value)) * MICROS_PER_UNIT).to_integral_value())


# ── Status ──

STATUS_READ_MAP = {
    "ENABLED": AdEntityStatus.ACTIVE,
    "PAUSED": AdEntityStatus.PAUSED,
    "REMOVED": AdEntityStatus.DELETED,
    "UNKNOWN": AdEntityStatus.UNKNOWN,
    "UNSPECIFIED": AdEntityStatus.UNKNOWN,
}

STATUS_WRITE_MAP = {
    AdEntityStatus.ACTIVE: "ENABLED",
    AdEntityStatus.PAUSED: "PAUSED",
}


def status_from_google(value: str) -> AdEntityStatus:
    """Map a Google entity status enum to the normalized status."""
    return STATUS_READ_MAP.get(value, AdEntityStatus.UNKNOWN)


def status_to_google(status: AdEntityStatus | str) -> str:
    """Map a normalized status to Google's enum. DELETED is handled via remove operations."""
    status = AdEntityStatus(status)
    google_status = STATUS_WRITE_MAP.get(status)
    if google_status is None:
        raise ValidationError(f"Google Ads cannot set status '{status}' via update (DELETED uses a remove operation).")
    return google_status


# ── Objective <-> advertisingChannelType heuristic ──

OBJECTIVE_WRITE_MAP = {
    AdObjective.SALES: "SEARCH",
    AdObjective.TRAFFIC: "SEARCH",
    AdObjective.LEADS: "SEARCH",
    AdObjective.AWARENESS: "DISPLAY",
    AdObjective.ENGAGEMENT: "DISPLAY",
    AdObjective.VIDEO_VIEWS: "VIDEO",
    AdObjective.APP_PROMOTION: "MULTI_CHANNEL",
    AdObjective.OTHER: "SEARCH",
}

CHANNEL_READ_MAP = {
    "VIDEO": AdObjective.VIDEO_VIEWS,
    "DISPLAY": AdObjective.AWARENESS,
    "MULTI_CHANNEL": AdObjective.APP_PROMOTION,
    "SHOPPING": AdObjective.SALES,
    "PERFORMANCE_MAX": AdObjective.SALES,
    "SEARCH": AdObjective.TRAFFIC,
}


def objective_to_channel_type(objective: AdObjective | str | None) -> str:
    """Map a normalized objective to Google's advertisingChannelType (heuristic)."""
    if objective is None:
        return "SEARCH"
    return OBJECTIVE_WRITE_MAP.get(AdObjective(objective), "SEARCH")


def objective_from_channel_type(channel_type: str) -> AdObjective:
    """Map Google's advertisingChannelType back to a normalized objective (heuristic)."""
    return CHANNEL_READ_MAP.get(channel_type, AdObjective.OTHER)


# ── Dates ──


def parse_google_date(value: str) -> datetime | None:
    """Parse a Google Ads "YYYY-MM-DD" date string into a datetime."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def format_google_date(value: datetime) -> str:
    """Format a datetime as a Google Ads "YYYY-MM-DD" date string."""
    return value.strftime("%Y-%m-%d")


# ── Entity mappers ──


def campaign_from_row(row: dict) -> AdCampaign:
    """Map a ``FROM campaign`` GAQL row to an AdCampaign DTO."""
    parsed = GoogleAdsCampaignRow.model_validate(row)
    campaign = parsed.campaign
    channel_type = campaign.advertisingChannelType
    return AdCampaign(
        id=str(campaign.id),
        name=campaign.name,
        status=status_from_google(campaign.status),
        objective=objective_from_channel_type(channel_type),
        daily_budget=micros_to_decimal(parsed.campaignBudget.amountMicros),
        currency=parsed.customer.currencyCode,
        start_time=parse_google_date(campaign.startDate),
        end_time=parse_google_date(campaign.endDate),
        extra={
            "advertising_channel_type": channel_type,
            "resource_name": campaign.resourceName,
        },
    )


def ad_group_from_row(row: dict) -> AdGroup:
    """Map a ``FROM ad_group`` GAQL row to an AdGroup DTO."""
    parsed = GoogleAdsAdGroupRow.model_validate(row)
    ad_group = parsed.adGroup
    return AdGroup(
        id=str(ad_group.id),
        campaign_id=str(parsed.campaign.id),
        name=ad_group.name,
        status=status_from_google(ad_group.status),
        bid_amount=micros_to_decimal(ad_group.cpcBidMicros),
        extra={"resource_name": ad_group.resourceName},
    )


def ad_from_row(row: dict) -> Ad:
    """Map a ``FROM ad_group_ad`` GAQL row to an Ad DTO.

    The creative is built from the first responsive search ad headline (title),
    first description (body), and first final URL (landing_url).
    """
    parsed = GoogleAdsAdGroupAdRow.model_validate(row)
    ad_group_ad = parsed.adGroupAd
    ad = ad_group_ad.ad
    rsa = ad.responsiveSearchAd or {}
    headlines = rsa.get("headlines", [])
    descriptions = rsa.get("descriptions", [])
    creative = AdCreative(
        title=headlines[0].get("text", "") if headlines else "",
        body=descriptions[0].get("text", "") if descriptions else "",
        landing_url=ad.finalUrls[0] if ad.finalUrls else "",
    )
    return Ad(
        id=str(ad.id),
        ad_group_id=str(parsed.adGroup.id),
        campaign_id=str(parsed.campaign.id),
        name=ad.name,
        status=status_from_google(ad_group_ad.status),
        creative=creative,
        extra={"resource_name": ad_group_ad.resourceName},
    )


# ── Insights ──


def _insights_entity_id(row: GoogleAdsMetricsRow, level: AdInsightsLevel) -> str:
    """Extract the entity id for the given aggregation level from an insights row."""
    if level == AdInsightsLevel.ACCOUNT:
        return str(row.customer.id)
    if level == AdInsightsLevel.CAMPAIGN:
        return str(row.campaign.id)
    if level == AdInsightsLevel.AD_GROUP:
        return str(row.adGroup.id)
    return str(row.adGroupAd.ad.id)


def insights_from_row(row: dict, level: AdInsightsLevel, currency: str) -> AdInsights:
    """Map an insights GAQL row (metrics.*) to the universal AdInsights DTO."""
    parsed = GoogleAdsMetricsRow.model_validate(row)
    metrics = parsed.metrics
    report_date = parse_google_date(parsed.segments.get("date", ""))
    return AdInsights(
        level=level,
        entity_id=_insights_entity_id(parsed, level),
        date_start=report_date,
        date_stop=report_date,
        impressions=int(metrics.impressions) if metrics.impressions is not None else None,
        clicks=int(metrics.clicks) if metrics.clicks is not None else None,
        spend=micros_to_decimal(metrics.costMicros),
        currency=parsed.customer.currencyCode or currency,
        ctr=float(metrics.ctr) if metrics.ctr is not None else None,
        cpc=micros_to_decimal(metrics.averageCpc),
        cpm=micros_to_decimal(metrics.averageCpm),
        conversions=float(metrics.conversions) if metrics.conversions is not None else None,
        conversion_value=Decimal(str(metrics.conversionsValue)) if metrics.conversionsValue is not None else None,
        video_views=int(metrics.videoViews) if metrics.videoViews is not None else None,
        extra={"segments": parsed.segments},
    )
