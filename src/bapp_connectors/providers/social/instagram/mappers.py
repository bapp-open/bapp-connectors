"""
Instagram Graph API <-> DTO mappers.

Converts raw Instagram Graph API payloads (IG user object, media edge,
insights) into the normalized social DTOs. Metrics the Graph API does not
return are left as ``None`` per the universal stats interface.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from bapp_connectors.core.dto import ProviderMeta
from bapp_connectors.core.dto.social import (
    SocialAccount,
    SocialAccountStats,
    SocialMediaType,
    SocialPost,
    SocialPostStats,
)

_HASHTAG_RE = re.compile(r"#(\w+)")

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


# ── Account ──


def account_from_ig(user: dict) -> SocialAccount:
    """Map an IG user object (Business/Creator account) to a SocialAccount."""
    username = user.get("username", "") or ""
    return SocialAccount(
        id=str(user.get("id", "")),
        username=username,
        display_name=user.get("name", "") or "",
        profile_url=f"https://www.instagram.com/{username}/" if username else "",
        avatar_url=user.get("profile_picture_url", "") or "",
        description=user.get("biography", "") or "",
        followers_count=user.get("followers_count"),
        following_count=user.get("follows_count"),
        posts_count=user.get("media_count"),
        extra={"website": user["website"]} if user.get("website") else {},
        provider_meta=ProviderMeta(
            provider="instagram",
            raw_id=str(user.get("id", "")),
            raw_payload=user,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Posts ──


def post_from_ig(media: dict) -> SocialPost:
    """Map an IG media object (media edge item) to a SocialPost."""
    media_id = str(media.get("id", ""))
    caption = media.get("caption", "") or ""

    published_at = None
    if timestamp := media.get("timestamp"):
        published_at = datetime.strptime(timestamp, _TIMESTAMP_FORMAT)

    return SocialPost(
        id=media_id,
        url=media.get("permalink", "") or "",
        description=caption,
        media_type=_media_type_from_media(media),
        media_url=media.get("media_url", "") or "",
        thumbnail_url=media.get("thumbnail_url", "") or "",
        published_at=published_at,
        hashtags=_HASHTAG_RE.findall(caption),
        stats=post_stats_from_ig(media),
        provider_meta=ProviderMeta(
            provider="instagram",
            raw_id=media_id,
            raw_payload=media,
            fetched_at=datetime.now(UTC),
        ),
    )


def _media_type_from_media(media: dict) -> SocialMediaType:
    """Derive the SocialMediaType from IG media_type/media_product_type (Reels are SHORT_VIDEO)."""
    media_type = media.get("media_type", "")
    if media_type == "IMAGE":
        return SocialMediaType.IMAGE
    if media_type == "VIDEO":
        if media.get("media_product_type") == "REELS":
            return SocialMediaType.SHORT_VIDEO
        return SocialMediaType.VIDEO
    if media_type == "CAROUSEL_ALBUM":
        return SocialMediaType.CAROUSEL
    return SocialMediaType.OTHER


# ── Stats ──


def post_stats_from_ig(media: dict, insights: dict | None = None) -> SocialPostStats:
    """
    Map media engagement fields (+ optional media insights) to SocialPostStats.

    ``insights`` is a flat dict of Graph metric name -> value, as produced by
    :func:`insights_to_dict`. Without insights only the engagement counters
    embedded in the media object (likes/comments) are populated.
    """
    likes = media.get("like_count")
    comments = media.get("comments_count")

    impressions = reach = saves = views = None
    if insights is not None:
        impressions = insights.get("impressions")
        reach = insights.get("reach")
        saves = insights.get("saved")
        views = insights.get("video_views")
        if views is None:
            views = insights.get("plays")

    engagement_rate = None
    if impressions:
        engagements = sum(v for v in (likes, comments) if v is not None)
        engagement_rate = engagements / impressions

    return SocialPostStats(
        post_id=str(media.get("id", "")),
        views=views,
        likes=likes,
        comments=comments,
        saves=saves,
        impressions=impressions,
        reach=reach,
        engagement_rate=engagement_rate,
        fetched_at=datetime.now(UTC),
    )


def account_stats_from_ig(user: dict, insights: dict | None) -> SocialAccountStats:
    """
    Map an IG user object (+ optional account insights totals) to SocialAccountStats.

    ``insights`` is a flat dict of Graph metric name -> value (e.g. daily
    values already summed into period totals via :func:`insights_to_totals`).
    """
    impressions = reach = None
    if insights is not None:
        impressions = insights.get("impressions")
        reach = insights.get("reach")

    return SocialAccountStats(
        account_id=str(user.get("id", "")),
        followers_count=user.get("followers_count"),
        posts_count=user.get("media_count"),
        impressions=impressions,
        reach=reach,
        fetched_at=datetime.now(UTC),
    )


# ── Insights helpers ──


def insights_to_dict(payload: dict) -> dict:
    """
    Flatten a Graph insights response into ``{metric_name: latest_value}``.

    Graph format: ``{"data": [{"name": ..., "values": [{"value": ...}, ...]}]}``
    — the last entry of ``values`` is the most recent.
    """
    result = {}
    for metric in payload.get("data", []):
        values = metric.get("values", [])
        if values:
            result[metric.get("name", "")] = values[-1].get("value")
    return result


def insights_to_totals(payload: dict) -> dict:
    """Flatten a period-scoped Graph insights response into ``{metric_name: sum_of_values}``."""
    result = {}
    for metric in payload.get("data", []):
        values = [v.get("value") for v in metric.get("values", [])]
        numeric = [v for v in values if isinstance(v, (int, float))]
        if numeric:
            result[metric.get("name", "")] = sum(numeric)
    return result
