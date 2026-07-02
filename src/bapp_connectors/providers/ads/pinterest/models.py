"""
Pydantic models for raw Pinterest API v5 payloads.

These model the raw Pinterest API — they are NOT normalized DTOs. All models
allow extra fields since Pinterest returns many optional attributes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PinterestCampaign(BaseModel):
    """Raw campaign object from ad_accounts/{id}/campaigns."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    ad_account_id: str = ""
    name: str = ""
    status: str = ""
    objective_type: str = ""
    daily_spend_cap: int | None = None  # micro-currency
    lifetime_spend_cap: int | None = None  # micro-currency
    start_time: int | None = None  # unix seconds
    end_time: int | None = None  # unix seconds


class PinterestAdGroup(BaseModel):
    """Raw ad group object from ad_accounts/{id}/ad_groups."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    ad_account_id: str = ""
    campaign_id: str = ""
    name: str = ""
    status: str = ""
    budget_in_micro_currency: int | None = None
    budget_type: str = ""  # DAILY / LIFETIME
    bid_in_micro_currency: int | None = None
    start_time: int | None = None  # unix seconds
    end_time: int | None = None  # unix seconds
    targeting_spec: dict = {}


class PinterestAd(BaseModel):
    """Raw ad object from ad_accounts/{id}/ads — promotes an existing Pin."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    ad_account_id: str = ""
    ad_group_id: str = ""
    campaign_id: str = ""
    name: str = ""
    status: str = ""
    creative_type: str = ""  # REGULAR for a promoted Pin
    pin_id: str = ""
    destination_url: str = ""


class PinterestAnalyticsRow(BaseModel):
    """One analytics row — a flat dict keyed by requested column names.

    Columns like ``SPEND_IN_DOLLAR``, ``IMPRESSION_1``, ``CLICKTHROUGH_1``
    arrive as top-level keys alongside the entity ID column
    (``CAMPAIGN_ID`` / ``AD_GROUP_ID`` / ``AD_ID``) and an optional ``DATE``.
    """

    model_config = ConfigDict(extra="allow")

    DATE: str = ""
