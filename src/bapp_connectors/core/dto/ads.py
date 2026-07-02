"""
Normalized DTOs for advertising platforms (Facebook/Meta Ads, TikTok Ads, Google Ads, ...).

Entity hierarchy is normalized to three levels:
    AdCampaign  →  AdGroup (Meta "ad set" / TikTok "adgroup" / Google "ad group")  →  Ad

``AdInsights`` is the *universal performance stats interface*: every platform maps
its native metric names onto the same fields. Metrics a platform does not expose
are ``None``; platform-specific extras go into ``extra``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .base import BaseDTO


class AdEntityStatus(StrEnum):
    """Normalized lifecycle status for campaigns, ad groups, and ads."""

    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"
    ARCHIVED = "archived"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    ENDED = "ended"
    DRAFT = "draft"
    UNKNOWN = "unknown"


class AdObjective(StrEnum):
    """Normalized campaign objective."""

    AWARENESS = "awareness"
    TRAFFIC = "traffic"
    ENGAGEMENT = "engagement"
    LEADS = "leads"
    APP_PROMOTION = "app_promotion"
    SALES = "sales"
    VIDEO_VIEWS = "video_views"
    OTHER = "other"


class AdInsightsLevel(StrEnum):
    """Aggregation level for performance insights."""

    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    AD_GROUP = "ad_group"
    AD = "ad"


class AdTargeting(BaseModel):
    """Normalized audience targeting. Platform-specific spec goes in ``extra``."""

    model_config = ConfigDict(frozen=True)

    countries: list[str] = []  # ISO 3166-1 alpha-2
    age_min: int | None = None
    age_max: int | None = None
    genders: list[str] = []  # "male", "female"
    interests: list[str] = []
    languages: list[str] = []
    extra: dict = {}


class AdCreative(BaseModel):
    """Normalized ad creative content."""

    model_config = ConfigDict(frozen=True)

    id: str = ""
    title: str = ""
    body: str = ""
    media_url: str = ""
    thumbnail_url: str = ""
    call_to_action: str = ""
    landing_url: str = ""
    extra: dict = {}


class AdCampaign(BaseDTO):
    """An advertising campaign. Leave ``id`` empty when creating."""

    id: str = ""
    name: str
    status: AdEntityStatus = AdEntityStatus.UNKNOWN
    objective: AdObjective | None = None
    daily_budget: Decimal | None = None
    lifetime_budget: Decimal | None = None
    currency: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    extra: dict = {}


class AdGroup(BaseDTO):
    """An ad group / ad set inside a campaign. Leave ``id`` empty when creating."""

    id: str = ""
    campaign_id: str
    name: str
    status: AdEntityStatus = AdEntityStatus.UNKNOWN
    daily_budget: Decimal | None = None
    lifetime_budget: Decimal | None = None
    bid_amount: Decimal | None = None
    targeting: AdTargeting | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    extra: dict = {}


class Ad(BaseDTO):
    """A single ad inside an ad group. Leave ``id`` empty when creating."""

    id: str = ""
    ad_group_id: str
    campaign_id: str = ""
    name: str
    status: AdEntityStatus = AdEntityStatus.UNKNOWN
    creative: AdCreative | None = None
    extra: dict = {}


class AdInsights(BaseModel):
    """
    Universal performance metrics for one entity over one period.

    ``None`` means the platform does not expose that metric.
    Platform-specific metrics are preserved in ``extra``.
    """

    model_config = ConfigDict(frozen=True)

    level: AdInsightsLevel
    entity_id: str = ""
    date_start: datetime | None = None
    date_stop: datetime | None = None
    impressions: int | None = None
    clicks: int | None = None
    spend: Decimal | None = None
    currency: str = ""
    ctr: float | None = None
    cpc: Decimal | None = None
    cpm: Decimal | None = None
    reach: int | None = None
    frequency: float | None = None
    conversions: float | None = None
    conversion_value: Decimal | None = None
    video_views: int | None = None
    extra: dict = {}
