"""
Pydantic models for Instagram Graph API response payloads.

These model the raw Graph API objects as consumed by the mappers — they are
NOT normalized DTOs. ``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class InstagramUser(BaseModel):
    """Raw IG user object — Business/Creator account (fields requested via ACCOUNT_FIELDS)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    username: str = ""
    name: str = ""
    biography: str = ""
    profile_picture_url: str = ""
    website: str = ""
    followers_count: int | None = None
    follows_count: int | None = None
    media_count: int | None = None


class InstagramMedia(BaseModel):
    """Raw IG media object (fields requested via MEDIA_FIELDS)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    caption: str = ""
    media_type: str = ""  # IMAGE | VIDEO | CAROUSEL_ALBUM
    media_product_type: str = ""  # AD | FEED | STORY | REELS
    media_url: str = ""
    permalink: str = ""
    thumbnail_url: str = ""
    timestamp: str = ""
    like_count: int | None = None
    comments_count: int | None = None


class InstagramMediaContainer(BaseModel):
    """Raw media container status object (``{creation_id}?fields=status_code,status``)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    status_code: str = ""  # EXPIRED | ERROR | FINISHED | IN_PROGRESS | PUBLISHED
    status: str = ""


class InstagramInsightsResult(BaseModel):
    """Raw Graph insights response (``{object_id}/insights``)."""

    model_config = ConfigDict(extra="allow")

    data: list[dict] = []
    paging: dict = {}
