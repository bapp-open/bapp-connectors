"""
Normalized DTOs for social media platforms (TikTok, YouTube Shorts, Facebook, ...).

The stats DTOs are the *universal stats interface*: every platform maps its
native metric names onto the same fields. Metrics a platform does not expose
are left as ``None`` (never 0 — 0 means "measured as zero"). Platform-specific
metrics that have no universal equivalent go into ``extra``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from .base import BaseDTO


class SocialMediaType(StrEnum):
    """The kind of media a social post contains."""

    VIDEO = "video"
    SHORT_VIDEO = "short_video"  # TikTok video, YouTube Short, FB Reel
    IMAGE = "image"
    CAROUSEL = "carousel"
    TEXT = "text"
    LIVE = "live"
    OTHER = "other"


class SocialPrivacy(StrEnum):
    """Normalized post visibility. Platforms map to their closest equivalent."""

    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class PublishStatus(StrEnum):
    """Lifecycle of a publish operation."""

    PUBLISHED = "published"
    PROCESSING = "processing"  # accepted by the platform, still transcoding/reviewing
    FAILED = "failed"


class SocialPostDraft(BaseModel):
    """
    A post to publish on a social platform.

    Media source: ``media_url`` (platform fetches it), ``file_path`` (local
    file), or ``content`` (raw bytes). Platform support differs — see the
    provider's connection guide. Text-only posts leave all three empty.
    """

    model_config = ConfigDict(frozen=True)

    title: str = ""
    description: str = ""
    media_type: SocialMediaType = SocialMediaType.VIDEO
    media_url: str = ""
    file_path: str = ""
    content: bytes | None = None
    filename: str = ""
    link: str = ""  # attached link for link/text posts
    privacy: SocialPrivacy = SocialPrivacy.PUBLIC
    tags: list[str] = []
    extra: dict = {}


class PublishResult(BaseModel):
    """
    Result of publishing a post.

    ``post_id`` may be empty while ``status`` is PROCESSING on platforms that
    publish asynchronously — poll ``check_publish_status`` with ``publish_id``.
    """

    model_config = ConfigDict(frozen=True)

    post_id: str = ""
    publish_id: str = ""  # platform handle for polling async publishes
    status: PublishStatus = PublishStatus.PUBLISHED
    url: str = ""
    error: str = ""
    extra: dict = {}


class SocialAccount(BaseDTO):
    """A social media account/channel/page."""

    id: str
    username: str = ""
    display_name: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    description: str = ""
    followers_count: int | None = None
    following_count: int | None = None
    posts_count: int | None = None
    is_verified: bool | None = None
    extra: dict = {}


class SocialPostStats(BaseModel):
    """
    Universal per-post statistics.

    ``None`` means the platform does not expose that metric.
    Platform-specific metrics are preserved in ``extra``.
    """

    model_config = ConfigDict(frozen=True)

    post_id: str = ""
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    impressions: int | None = None
    reach: int | None = None
    clicks: int | None = None
    engagement_rate: float | None = None
    watch_time_seconds: float | None = None
    avg_watch_time_seconds: float | None = None
    fetched_at: datetime | None = None
    extra: dict = {}

    @property
    def engagements(self) -> int | None:
        """Sum of the interaction metrics the platform exposes (None if none are)."""
        parts = [v for v in (self.likes, self.comments, self.shares, self.saves) if v is not None]
        return sum(parts) if parts else None


class SocialAccountStats(BaseModel):
    """
    Universal account-level statistics, optionally scoped to a period.

    ``None`` means the platform does not expose that metric.
    """

    model_config = ConfigDict(frozen=True)

    account_id: str = ""
    followers_count: int | None = None
    following_count: int | None = None
    posts_count: int | None = None
    total_views: int | None = None
    total_likes: int | None = None
    impressions: int | None = None
    reach: int | None = None
    engagement_rate: float | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    fetched_at: datetime | None = None
    extra: dict = {}


class SocialPost(BaseDTO):
    """A post/video published on a social platform."""

    id: str
    account_id: str = ""
    url: str = ""
    title: str = ""
    description: str = ""
    media_type: SocialMediaType = SocialMediaType.OTHER
    media_url: str = ""
    thumbnail_url: str = ""
    duration_seconds: float | None = None
    published_at: datetime | None = None
    hashtags: list[str] = []
    stats: SocialPostStats | None = None
    extra: dict = {}
