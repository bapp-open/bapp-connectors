"""
Pydantic models for Threads API response payloads.

These model the raw Threads API objects as consumed by the mappers — they are
NOT normalized DTOs. ``extra="allow"`` preserves fields we do not model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ThreadsUser(BaseModel):
    """Raw Threads user object (``me`` with the profile fields)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    username: str = ""
    name: str = ""
    threads_profile_picture_url: str = ""
    threads_biography: str = ""


class ThreadsMedia(BaseModel):
    """Raw Threads media object (``me/threads`` edge item or single media)."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    text: str = ""
    media_type: str = ""
    media_url: str = ""
    permalink: str = ""
    timestamp: str = ""
    username: str = ""
    is_quote_post: bool | None = None


class ThreadsInsightsResult(BaseModel):
    """Raw Threads insights response (``{media_id}/insights`` or ``me/threads_insights``)."""

    model_config = ConfigDict(extra="allow")

    data: list[dict] = []
    paging: dict = {}
