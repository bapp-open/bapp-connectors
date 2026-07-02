"""
YouTube <-> DTO mappers.

Converts between raw YouTube Data API v3 payloads and normalized framework DTOs.
"""

from __future__ import annotations

import re
from datetime import datetime

from bapp_connectors.core.dto.social import (
    PublishResult,
    PublishStatus,
    SocialAccount,
    SocialAccountStats,
    SocialMediaType,
    SocialPost,
    SocialPostDraft,
    SocialPostStats,
    SocialPrivacy,
)
from bapp_connectors.providers.social.youtube.models import YouTubeChannel, YouTubeVideo

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
_HASHTAG_RE = re.compile(r"#\w+")

# Thumbnail sizes from best to worst.
_THUMBNAIL_PREFERENCE = ("maxres", "standard", "high", "medium", "default")


def parse_iso8601_duration(value: str) -> float:
    """Parse an ISO 8601 duration ("PT#H#M#S" forms, bare "PT#S", "P0D") into seconds."""
    match = _DURATION_RE.match(value or "")
    if not match:
        return 0.0
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _parse_rfc3339(value: str) -> datetime | None:
    """Parse an RFC 3339 timestamp (e.g. "2024-05-01T10:00:00Z")."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    """Convert a YouTube string counter to int; missing/invalid → None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _best_thumbnail(thumbnails: dict) -> str:
    """Pick the highest-resolution thumbnail URL available."""
    for size in _THUMBNAIL_PREFERENCE:
        if url := thumbnails.get(size, {}).get("url", ""):
            return url
    return ""


def _extract_hashtags(*texts: str) -> list[str]:
    """Extract #hashtags from the given texts, lowercased and deduped (order preserved)."""
    seen: dict[str, None] = {}
    for text in texts:
        for tag in _HASHTAG_RE.findall(text or ""):
            seen.setdefault(tag.lower())
    return list(seen)


# ── Account ──


def account_from_channel(channel: dict) -> SocialAccount:
    """Map a YouTube channel resource to a SocialAccount."""
    ch = YouTubeChannel.model_validate(channel)
    snippet = ch.snippet
    statistics = ch.statistics
    custom_url = snippet.get("customUrl", "")

    followers_count = None
    if not statistics.get("hiddenSubscriberCount"):
        followers_count = _to_int(statistics.get("subscriberCount"))

    return SocialAccount(
        id=ch.id,
        username=custom_url,
        display_name=snippet.get("title", ""),
        profile_url=f"https://www.youtube.com/{custom_url}" if custom_url else "",
        avatar_url=_best_thumbnail(snippet.get("thumbnails", {})),
        description=snippet.get("description", ""),
        followers_count=followers_count,
        posts_count=_to_int(statistics.get("videoCount")),
        extra={
            "uploads_playlist_id": ch.contentDetails.get("relatedPlaylists", {}).get("uploads", ""),
        },
    )


def account_stats_from_channel(channel: dict) -> SocialAccountStats:
    """Map a YouTube channel resource to universal account statistics (lifetime counters)."""
    ch = YouTubeChannel.model_validate(channel)
    statistics = ch.statistics

    followers_count = None
    if not statistics.get("hiddenSubscriberCount"):
        followers_count = _to_int(statistics.get("subscriberCount"))

    return SocialAccountStats(
        account_id=ch.id,
        followers_count=followers_count,
        posts_count=_to_int(statistics.get("videoCount")),
        total_views=_to_int(statistics.get("viewCount")),
    )


# ── Posts ──


def stats_from_video(video: dict) -> SocialPostStats:
    """Map a YouTube video resource to universal post statistics."""
    v = YouTubeVideo.model_validate(video)
    statistics = v.statistics
    views = _to_int(statistics.get("viewCount"))
    likes = _to_int(statistics.get("likeCount"))
    comments = _to_int(statistics.get("commentCount"))

    engagement_rate = None
    if views:
        engagement_rate = ((likes or 0) + (comments or 0)) / views

    return SocialPostStats(
        post_id=v.id,
        views=views,
        likes=likes,
        comments=comments,
        shares=None,  # not exposed by the Data API
        engagement_rate=engagement_rate,
    )


def post_from_video(video: dict, shorts_max_seconds: int = 180) -> SocialPost:
    """Map a YouTube video resource to a SocialPost.

    Videos not longer than ``shorts_max_seconds`` are classified as SHORT_VIDEO.
    """
    v = YouTubeVideo.model_validate(video)
    snippet = v.snippet
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    duration_seconds = parse_iso8601_duration(v.contentDetails.get("duration", ""))
    media_type = SocialMediaType.SHORT_VIDEO if duration_seconds <= shorts_max_seconds else SocialMediaType.VIDEO

    return SocialPost(
        id=v.id,
        account_id=snippet.get("channelId", ""),
        url=f"https://www.youtube.com/watch?v={v.id}",
        title=title,
        description=description,
        media_type=media_type,
        thumbnail_url=_best_thumbnail(snippet.get("thumbnails", {})),
        duration_seconds=duration_seconds,
        published_at=_parse_rfc3339(snippet.get("publishedAt", "")),
        hashtags=_extract_hashtags(description, title),
        stats=stats_from_video(video),
    )


# ── Publishing ──

PRIVACY_TO_YOUTUBE = {
    SocialPrivacy.PUBLIC: "public",
    SocialPrivacy.PRIVATE: "private",
    SocialPrivacy.UNLISTED: "unlisted",
}


def draft_to_video_metadata(draft: SocialPostDraft) -> dict:
    """Map a SocialPostDraft to videos.insert metadata (snippet + status parts)."""
    snippet: dict = {
        "title": draft.title or "Untitled",
        "description": draft.description,
    }
    if draft.tags:
        snippet["tags"] = draft.tags
    if category_id := draft.extra.get("category_id"):
        snippet["categoryId"] = category_id
    return {
        "snippet": snippet,
        "status": {
            "privacyStatus": PRIVACY_TO_YOUTUBE[draft.privacy],
            "selfDeclaredMadeForKids": draft.extra.get("made_for_kids", False),
        },
    }


def publish_result_from_video(video: dict) -> PublishResult:
    """Map an uploaded video resource to a PublishResult.

    The video id exists immediately after upload and its watch page is live,
    so the result is PUBLISHED even while YouTube still processes the file.
    """
    video_id = video.get("id", "")
    return PublishResult(
        post_id=video_id,
        publish_id=video_id,
        status=PublishStatus.PUBLISHED,
        url=f"https://www.youtube.com/watch?v={video_id}",
        extra={"upload_status": video.get("status", {}).get("uploadStatus", "")},
    )
