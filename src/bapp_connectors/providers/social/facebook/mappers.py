"""
Facebook Graph API <-> DTO mappers.

Converts raw Graph API payloads for a Facebook Page (page object, posts edge,
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

_CREATED_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_MEDIA_TYPE_MAP = {
    "video": SocialMediaType.VIDEO,
    "photo": SocialMediaType.IMAGE,
    "album": SocialMediaType.CAROUSEL,
}


# ── Account ──


def account_from_page(page: dict) -> SocialAccount:
    """Map a Graph Page object to a SocialAccount."""
    verification_status = page.get("verification_status")
    return SocialAccount(
        id=str(page.get("id", "")),
        username=page.get("username", "") or "",
        display_name=page.get("name", "") or "",
        profile_url=page.get("link", "") or "",
        avatar_url=(page.get("picture") or {}).get("data", {}).get("url", ""),
        description=page.get("about", "") or "",
        followers_count=page.get("followers_count", page.get("fan_count")),
        is_verified=None if verification_status is None else verification_status == "blue_verified",
        provider_meta=ProviderMeta(
            provider="facebook",
            raw_id=str(page.get("id", "")),
            raw_payload=page,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Posts ──


def post_from_graph(post: dict) -> SocialPost:
    """Map a Graph Page post object (posts edge item) to a SocialPost."""
    post_id = str(post.get("id", ""))
    message = post.get("message", "") or ""

    published_at = None
    if created_time := post.get("created_time"):
        published_at = datetime.strptime(created_time, _CREATED_TIME_FORMAT)

    return SocialPost(
        id=post_id,
        account_id=post_id.split("_", 1)[0] if "_" in post_id else "",
        url=post.get("permalink_url", "") or "",
        description=message,
        media_type=_media_type_from_post(post),
        thumbnail_url=post.get("full_picture", "") or "",
        published_at=published_at,
        hashtags=_HASHTAG_RE.findall(message),
        stats=post_stats_from_graph(post),
        provider_meta=ProviderMeta(
            provider="facebook",
            raw_id=post_id,
            raw_payload=post,
            fetched_at=datetime.now(UTC),
        ),
    )


def _media_type_from_post(post: dict) -> SocialMediaType:
    """Derive the SocialMediaType from the post's first attachment (TEXT when none)."""
    attachments = (post.get("attachments") or {}).get("data", [])
    if not attachments:
        return SocialMediaType.TEXT
    media_type = attachments[0].get("media_type", "")
    return _MEDIA_TYPE_MAP.get(media_type, SocialMediaType.OTHER)


# ── Stats ──


def _summary_count(edge: dict | None) -> int | None:
    """Extract ``summary.total_count`` from a summarized edge (likes/comments)."""
    if not edge:
        return None
    return (edge.get("summary") or {}).get("total_count")


def post_stats_from_graph(post: dict, insights: dict | None = None) -> SocialPostStats:
    """
    Map post engagement fields (+ optional post insights) to SocialPostStats.

    ``insights`` is a flat dict of Graph metric name -> value, as produced by
    :func:`insights_to_dict`. Without insights only the engagement counters
    embedded in the post object (likes/comments/shares) are populated.
    """
    likes = _summary_count(post.get("likes"))
    comments = _summary_count(post.get("comments"))
    shares = (post.get("shares") or {}).get("count")

    impressions = reach = clicks = views = None
    if insights is not None:
        impressions = insights.get("post_impressions")
        reach = insights.get("post_impressions_unique")
        clicks = insights.get("post_clicks")
        views = insights.get("post_video_views")

    engagement_rate = None
    if impressions:
        engagements = sum(v for v in (likes, comments, shares) if v is not None)
        engagement_rate = engagements / impressions

    return SocialPostStats(
        post_id=str(post.get("id", "")),
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        impressions=impressions,
        reach=reach,
        clicks=clicks,
        engagement_rate=engagement_rate,
        fetched_at=datetime.now(UTC),
    )


def account_stats_from_page(page: dict, insights: dict | None) -> SocialAccountStats:
    """
    Map a Graph Page object (+ optional page insights totals) to SocialAccountStats.

    ``insights`` is a flat dict of Graph metric name -> value (e.g. daily
    values already summed into period totals via :func:`insights_to_totals`).
    """
    impressions = reach = None
    if insights is not None:
        impressions = insights.get("page_impressions")
        reach = insights.get("page_impressions_unique")

    return SocialAccountStats(
        account_id=str(page.get("id", "")),
        followers_count=page.get("followers_count", page.get("fan_count")),
        posts_count=None,
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
