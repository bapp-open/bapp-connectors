"""
Pydantic models for raw Meta Marketing API payloads.

These model the raw Graph API — they are NOT normalized DTOs. Budgets and bid
amounts are minor currency units (cents) serialized as strings; insights spend
is in currency units.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MetaCampaign(BaseModel):
    """Raw Marketing API campaign object."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    status: str = ""
    effective_status: str = ""
    objective: str = ""
    daily_budget: str | None = None
    lifetime_budget: str | None = None
    special_ad_categories: list[str] = []
    start_time: str | None = None
    stop_time: str | None = None


class MetaAdSet(BaseModel):
    """Raw Marketing API ad set object."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    campaign_id: str = ""
    name: str = ""
    status: str = ""
    effective_status: str = ""
    daily_budget: str | None = None
    lifetime_budget: str | None = None
    bid_amount: str | None = None
    billing_event: str = ""
    optimization_goal: str = ""
    targeting: dict = {}
    start_time: str | None = None
    end_time: str | None = None


class MetaAd(BaseModel):
    """Raw Marketing API ad object."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    adset_id: str = ""
    campaign_id: str = ""
    name: str = ""
    status: str = ""
    effective_status: str = ""
    creative: dict = {}


class MetaInsightsRow(BaseModel):
    """One row from the insights edge."""

    model_config = ConfigDict(extra="allow")

    impressions: str | None = None
    clicks: str | None = None
    spend: str | None = None
    ctr: str | None = None
    cpc: str | None = None
    cpm: str | None = None
    reach: str | None = None
    frequency: str | None = None
    account_currency: str = ""
    actions: list[dict] = []
    action_values: list[dict] = []
    video_play_actions: list[dict] = []
    date_start: str | None = None
    date_stop: str | None = None
