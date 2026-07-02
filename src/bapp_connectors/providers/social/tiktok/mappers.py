"""
TikTok <-> DTO mappers.

Converts raw TikTok Display API v2 payloads into normalized framework DTOs.
TikTok metrics map onto the universal stats interface; metrics TikTok does
not expose (saves, impressions, reach, clicks) stay ``None``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from bapp_connectors.core.dto.social import (
    SocialAccount,
    SocialAccountStats,
    SocialMediaType,
    SocialPost,
    SocialPostStats,
)
from bapp_connectors.providers.social.tiktok.models import TikTokUser, TikTokVideo

_HASHTAG_RE = re.compile(r"#(\w+)")


def _extract_hashtags(*texts: str) -> list[str]:
    """Extract lowercase, de-duplicated hashtags from the given texts, in order of appearance."""
    seen: dict[str, None] = {}
    for text in texts:
        for tag in _HASHTAG_RE.findall(text or ""):
            seen.setdefault(tag.lower())
    return list(seen)


def account_from_tiktok(user: dict) -> SocialAccount:
    """Map a TikTok user/info/ user object to a SocialAccount."""
    u = TikTokUser.model_validate(user)
    return SocialAccount(
        id=u.open_id,
        username=u.username,
        display_name=u.display_name,
        profile_url=u.profile_deep_link,
        avatar_url=u.avatar_url,
        description=u.bio_description,
        followers_count=u.follower_count,
        following_count=u.following_count,
        posts_count=u.video_count,
        is_verified=u.is_verified,
    )


def post_stats_from_tiktok(video: dict) -> SocialPostStats:
    """Map a TikTok video object to universal per-post statistics."""
    v = TikTokVideo.model_validate(video)
    engagement_rate = None
    if v.view_count is not None and v.view_count > 0:
        interactions = (v.like_count or 0) + (v.comment_count or 0) + (v.share_count or 0)
        engagement_rate = interactions / v.view_count
    return SocialPostStats(
        post_id=v.id,
        views=v.view_count,
        likes=v.like_count,
        comments=v.comment_count,
        shares=v.share_count,
        engagement_rate=engagement_rate,
    )


def post_from_tiktok(video: dict) -> SocialPost:
    """Map a TikTok video object to a SocialPost with embedded stats."""
    v = TikTokVideo.model_validate(video)
    published_at = None
    if v.create_time is not None:
        published_at = datetime.fromtimestamp(v.create_time, tz=UTC)
    return SocialPost(
        id=v.id,
        url=v.share_url,
        title=v.title,
        description=v.video_description,
        media_type=SocialMediaType.SHORT_VIDEO,
        thumbnail_url=v.cover_image_url,
        duration_seconds=float(v.duration) if v.duration is not None else None,
        published_at=published_at,
        hashtags=_extract_hashtags(v.video_description, v.title),
        stats=post_stats_from_tiktok(video),
        extra={"embed_link": v.embed_link} if v.embed_link else {},
    )


def account_stats_from_tiktok(user: dict) -> SocialAccountStats:
    """Map a TikTok user/info/ user object to universal account statistics.

    TikTok exposes lifetime counters only; total_views is not available.
    """
    u = TikTokUser.model_validate(user)
    return SocialAccountStats(
        account_id=u.open_id,
        followers_count=u.follower_count,
        following_count=u.following_count,
        posts_count=u.video_count,
        total_likes=u.likes_count,
    )
