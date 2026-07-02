"""
Pydantic models for Facebook Graph API response payloads.

These model the raw Graph API objects as consumed by the mappers — they are
NOT normalized DTOs. ``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FacebookPicture(BaseModel):
    """Page profile picture wrapper (``picture{url}`` field expansion)."""

    model_config = ConfigDict(extra="allow")

    data: dict = {}


class FacebookPage(BaseModel):
    """Raw Facebook Page object (fields requested via PAGE_FIELDS)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    username: str = ""
    link: str = ""
    about: str = ""
    followers_count: int | None = None
    fan_count: int | None = None
    picture: FacebookPicture | None = None
    verification_status: str | None = None


class FacebookPost(BaseModel):
    """Raw Facebook Page post object (fields requested via POST_FIELDS)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    message: str = ""
    created_time: str = ""
    permalink_url: str = ""
    full_picture: str = ""
    attachments: dict | None = None
    shares: dict | None = None
    likes: dict | None = None
    comments: dict | None = None


class FacebookInsightsResult(BaseModel):
    """Raw Graph insights response (``{object_id}/insights``)."""

    model_config = ConfigDict(extra="allow")

    data: list[dict] = []
    paging: dict = {}
