"""
Threads API <-> DTO mappers.

Converts raw Threads API payloads (user object, threads edge, media/user
insights) into the normalized social DTOs. Metrics the API does not return
are left as ``None`` per the universal stats interface; Threads-specific
metrics (reposts, quotes, replies at account level) go into ``extra``.
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
from bapp_connectors.providers.social.threads.models import ThreadsMedia, ThreadsUser

_HASHTAG_RE = re.compile(r"#(\w+)")

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_MEDIA_TYPE_MAP = {
    "TEXT_POST": SocialMediaType.TEXT,
    "IMAGE": SocialMediaType.IMAGE,
    "VIDEO": SocialMediaType.VIDEO,
    "CAROUSEL_ALBUM": SocialMediaType.CAROUSEL,
    "REPOST_FACADE": SocialMediaType.OTHER,
}


# ── Account ──


def account_from_threads(user: dict) -> SocialAccount:
    """Map a Threads user object (``me`` profile fields) to a SocialAccount.

    The profile object carries no follower count — the adapter fills
    ``followers_count`` from user insights when available.
    """
    u = ThreadsUser.model_validate(user)
    return SocialAccount(
        id=u.id,
        username=u.username,
        display_name=u.name,
        profile_url=f"https://www.threads.net/@{u.username}" if u.username else "",
        avatar_url=u.threads_profile_picture_url,
        description=u.threads_biography,
    )


# ── Posts ──


def post_from_threads(media: dict) -> SocialPost:
    """Map a Threads media object to a SocialPost."""
    m = ThreadsMedia.model_validate(media)

    published_at = None
    if m.timestamp:
        published_at = datetime.strptime(m.timestamp, _TIMESTAMP_FORMAT)

    extra = {}
    if m.username:
        extra["username"] = m.username
    if m.is_quote_post is not None:
        extra["is_quote_post"] = m.is_quote_post

    return SocialPost(
        id=m.id,
        url=m.permalink,
        description=m.text,
        media_type=_MEDIA_TYPE_MAP.get(m.media_type, SocialMediaType.OTHER),
        media_url=m.media_url,
        published_at=published_at,
        hashtags=_HASHTAG_RE.findall(m.text),
        extra=extra,
    )


# ── Stats ──


def post_stats_from_insights(post_id: str, payload: dict | None) -> SocialPostStats:
    """Map a Threads media insights response to universal per-post statistics.

    Threads metrics: views, likes, replies (→ comments), shares, reposts,
    quotes. ``shares`` maps to the universal field, falling back to ``reposts``
    when the API does not return shares; reposts and quotes are always kept in
    ``extra``. ``payload=None`` (insights unavailable) yields all-``None`` stats.
    """
    if payload is None:
        return SocialPostStats(post_id=post_id, fetched_at=datetime.now(UTC))

    metrics = insights_to_dict(payload)
    shares = metrics["shares"] if "shares" in metrics else metrics.get("reposts")
    return SocialPostStats(
        post_id=post_id,
        views=metrics.get("views"),
        likes=metrics.get("likes"),
        comments=metrics.get("replies"),
        shares=shares,
        fetched_at=datetime.now(UTC),
        extra={k: metrics[k] for k in ("reposts", "quotes") if k in metrics},
    )


def account_stats_from_insights(payload: dict) -> SocialAccountStats:
    """Map a Threads user insights response (``me/threads_insights``) to SocialAccountStats.

    ``followers_count`` is the lifetime follower total; views/likes are the
    period totals. Threads-specific counters (replies, reposts, quotes) go
    into ``extra``.
    """
    metrics = insights_to_dict(payload)
    return SocialAccountStats(
        followers_count=metrics.get("followers_count"),
        total_views=metrics.get("views"),
        total_likes=metrics.get("likes"),
        fetched_at=datetime.now(UTC),
        extra={k: metrics[k] for k in ("replies", "reposts", "quotes") if k in metrics},
    )


# ── Insights helpers ──


def insights_to_dict(payload: dict) -> dict:
    """Flatten a Threads insights response into ``{metric_name: value}``.

    Threads returns metrics in two shapes:
    ``{"name": ..., "total_value": {"value": ...}}`` for totals, and
    ``{"name": ..., "values": [{"value": ...}, ...]}`` for time series —
    series values are summed into a period total.
    """
    result = {}
    for metric in payload.get("data", []):
        name = metric.get("name", "")
        total_value = metric.get("total_value")
        if isinstance(total_value, dict) and "value" in total_value:
            result[name] = total_value["value"]
            continue
        values = [v.get("value") for v in metric.get("values", [])]
        numeric = [v for v in values if isinstance(v, (int, float))]
        if numeric:
            result[name] = sum(numeric)
    return result
