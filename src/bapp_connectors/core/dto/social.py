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


class SocialFormat(StrEnum):
    """Publishing surface on a channel (feed post, reel, short)."""

    POST = "post"
    REEL = "reel"
    SHORT = "short"


class SocialMention(BaseModel):
    """An account tagged/mentioned in a post."""

    model_config = ConfigDict(frozen=True)

    username: str
    id: str = ""
    name: str = ""
    avatar_url: str = ""


class SocialProductTag(BaseModel):
    """A catalog product tagged in a post (shopping tags)."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    image_url: str = ""
    extra: dict = {}


class SocialLocation(BaseModel):
    """A place attached to a post."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    address: str = ""


class SocialFormatProfile(BaseModel):
    """
    What a channel accepts for one format.

    ``None`` limits mean "no known limit"; ``0`` means "not accepted at all".
    """

    model_config = ConfigDict(frozen=True)

    format: SocialFormat
    media_types: list[SocialMediaType]
    max_text_length: int | None = None
    max_title_length: int | None = None
    requires_title: bool = False
    max_hashtags: int | None = None
    supports_mentions: bool = False
    max_mentions: int | None = None
    supports_product_tags: bool = False
    supports_location: bool = False
    min_video_seconds: int | None = None
    max_video_seconds: int | None = None
    vertical_only: bool = False
    max_file_bytes: int | None = None


class SocialPublishProfile(BaseModel):
    """The formats a channel can publish. Empty = channel declares no profile."""

    model_config = ConfigDict(frozen=True)

    formats: list[SocialFormatProfile] = []

    def for_format(self, fmt: SocialFormat) -> SocialFormatProfile | None:
        return next((p for p in self.formats if p.format == fmt), None)


class SocialDestination(BaseModel):
    """
    A publish target reachable through one connection (a Facebook page, an
    Instagram business account, ...). ``kind`` is provider-defined, e.g.
    ``"facebook_page"`` or ``"instagram_account"``; ``credentials`` holds the
    destination-scoped secrets (e.g. a page access token).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    provider: str
    kind: str
    name: str
    username: str = ""
    avatar_url: str = ""
    credentials: dict = {}


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
    format: SocialFormat = SocialFormat.POST
    hashtags: list[str] = []
    mentions: list[SocialMention] = []
    product_tags: list[SocialProductTag] = []
    location: SocialLocation | None = None


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
