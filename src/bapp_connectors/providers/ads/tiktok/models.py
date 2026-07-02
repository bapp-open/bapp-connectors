"""
Pydantic models for raw TikTok Business API payloads.

These model the raw TikTok API — they are NOT normalized DTOs. All models
allow extra fields since TikTok returns many optional attributes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TikTokCampaign(BaseModel):
    """Raw campaign object from campaign/get/."""

    model_config = ConfigDict(extra="allow")

    campaign_id: str = ""
    campaign_name: str = ""
    operation_status: str = ""
    secondary_status: str = ""
    objective_type: str = ""
    budget_mode: str = ""
    budget: float | None = None
    create_time: str = ""
    modify_time: str = ""


class TikTokAdGroup(BaseModel):
    """Raw ad group object from adgroup/get/."""

    model_config = ConfigDict(extra="allow")

    adgroup_id: str = ""
    adgroup_name: str = ""
    campaign_id: str = ""
    operation_status: str = ""
    secondary_status: str = ""
    budget_mode: str = ""
    budget: float | None = None
    bid_price: float | None = None
    schedule_start_time: str = ""
    schedule_end_time: str = ""
    location_ids: list[str] = []
    age_groups: list[str] = []
    gender: str = ""


class TikTokAd(BaseModel):
    """Raw ad object from ad/get/."""

    model_config = ConfigDict(extra="allow")

    ad_id: str = ""
    ad_name: str = ""
    adgroup_id: str = ""
    campaign_id: str = ""
    operation_status: str = ""
    secondary_status: str = ""
    ad_text: str = ""
    call_to_action: str = ""
    landing_page_url: str = ""
    video_id: str = ""
    image_ids: list[str] = []


class TikTokReportRow(BaseModel):
    """One row from report/integrated/get/ — dimensions + stringified metrics."""

    model_config = ConfigDict(extra="allow")

    dimensions: dict = {}
    metrics: dict = {}
