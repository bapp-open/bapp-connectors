"""
Pydantic models for TikTok Display API v2 response payloads.

These model the raw TikTok API — they are NOT normalized DTOs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TikTokUser(BaseModel):
    """TikTok user object from user/info/."""

    model_config = ConfigDict(extra="allow")

    open_id: str = ""
    union_id: str = ""
    avatar_url: str = ""
    display_name: str = ""
    username: str = ""
    bio_description: str = ""
    profile_deep_link: str = ""
    is_verified: bool | None = None
    follower_count: int | None = None
    following_count: int | None = None
    likes_count: int | None = None
    video_count: int | None = None


class TikTokVideo(BaseModel):
    """TikTok video object from video/list/ and video/query/."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    title: str = ""
    video_description: str = ""
    create_time: int | None = None
    cover_image_url: str = ""
    share_url: str = ""
    duration: float | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    embed_link: str = ""
