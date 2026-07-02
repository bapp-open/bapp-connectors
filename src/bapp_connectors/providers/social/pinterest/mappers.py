"""
Pinterest <-> DTO mappers.

Converts raw Pinterest API v5 payloads into normalized framework DTOs.
Pinterest metrics map onto the universal stats interface; metrics Pinterest
does not expose (views, likes, comments, shares) stay ``None``. OUTBOUND_CLICK
is folded into ``clicks`` and preserved separately in ``extra``.
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
from bapp_connectors.providers.social.pinterest.models import PinterestPin, PinterestUserAccount

_HASHTAG_RE = re.compile(r"#(\w+)")

_MEDIA_TYPE_MAP = {
    "image": SocialMediaType.IMAGE,
    "video": SocialMediaType.VIDEO,
}

# Pinterest renders pin images in several sizes; prefer the largest.
_IMAGE_SIZE_PREFERENCE = ("originals", "1200x", "600x", "400x300", "150x150")


def _extract_hashtags(*texts: str) -> list[str]:
    """Extract lowercase, de-duplicated hashtags from the given texts, in order of appearance."""
    seen: dict[str, None] = {}
    for text in texts:
        for tag in _HASHTAG_RE.findall(text or ""):
            seen.setdefault(tag.lower())
    return list(seen)


def _parse_created_at(value: str | None) -> datetime | None:
    """Parse Pinterest's ISO 8601 ``created_at`` (may end in "Z", may be naive UTC)."""
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _best_image_url(images: dict) -> str:
    """Pick the URL of the best (largest) rendered image size."""
    for size in _IMAGE_SIZE_PREFERENCE:
        entry = images.get(size)
        if isinstance(entry, dict) and entry.get("url"):
            return entry["url"]
    for entry in images.values():
        if isinstance(entry, dict) and entry.get("url"):
            return entry["url"]
    return ""


def _lifetime_metrics(payload: dict) -> dict:
    """Extract the metric dict from a v5 analytics payload.

    Shape: ``{"all": {"lifetime_metrics": {"IMPRESSION": n, ...}}}`` —
    ``summary_metrics`` is tolerated as an alternative key.
    """
    scope = payload.get("all") or {}
    return scope.get("lifetime_metrics") or scope.get("summary_metrics") or {}


# ── Account ──


def account_from_pinterest(user: dict) -> SocialAccount:
    """Map a Pinterest user_account object to a SocialAccount."""
    u = PinterestUserAccount.model_validate(user)
    return SocialAccount(
        id=u.id or u.username,
        username=u.username,
        profile_url=f"https://www.pinterest.com/{u.username}/",
        avatar_url=u.profile_image,
        description=u.about,
        followers_count=u.follower_count,
        following_count=u.following_count,
        posts_count=u.pin_count,
        extra={"monthly_views": u.monthly_views} if u.monthly_views is not None else {},
    )


# ── Pins ──


def post_from_pin(pin: dict) -> SocialPost:
    """Map a Pinterest pin object to a SocialPost."""
    p = PinterestPin.model_validate(pin)
    media = p.media
    return SocialPost(
        id=p.id,
        url=f"https://www.pinterest.com/pin/{p.id}/",
        title=p.title or "",
        description=p.description or "",
        media_type=_MEDIA_TYPE_MAP.get(media.media_type if media else "", SocialMediaType.OTHER),
        thumbnail_url=_best_image_url(media.images) if media else "",
        published_at=_parse_created_at(p.created_at),
        hashtags=_extract_hashtags(p.description or "", p.title or ""),
        extra={"board_id": p.board_id} if p.board_id else {},
    )


# ── Stats ──


def stats_from_pin_analytics(pin_id: str, payload: dict) -> SocialPostStats:
    """Map a pins/{id}/analytics payload to universal per-pin statistics.

    Pinterest does not expose views/likes/comments here — they stay ``None``.
    ``clicks`` is PIN_CLICK + OUTBOUND_CLICK; OUTBOUND_CLICK is also preserved
    in ``extra``.
    """
    metrics = _lifetime_metrics(payload)
    pin_clicks = metrics.get("PIN_CLICK")
    outbound_clicks = metrics.get("OUTBOUND_CLICK")
    clicks = None
    if pin_clicks is not None or outbound_clicks is not None:
        clicks = (pin_clicks or 0) + (outbound_clicks or 0)
    return SocialPostStats(
        post_id=pin_id,
        saves=metrics.get("SAVE"),
        impressions=metrics.get("IMPRESSION"),
        clicks=clicks,
        fetched_at=datetime.now(UTC),
        extra={"outbound_clicks": outbound_clicks} if outbound_clicks is not None else {},
    )


def account_stats_from_analytics(payload: dict, user: dict) -> SocialAccountStats:
    """Map a user_account/analytics payload (+ user_account object) to SocialAccountStats.

    The analytics payload carries the same metric dict shape as pin analytics;
    lifetime counters (followers, pin count) come from the user object.
    """
    metrics = _lifetime_metrics(payload)
    u = PinterestUserAccount.model_validate(user)
    return SocialAccountStats(
        account_id=u.id or u.username,
        followers_count=u.follower_count,
        following_count=u.following_count,
        posts_count=u.pin_count,
        impressions=metrics.get("IMPRESSION"),
        fetched_at=datetime.now(UTC),
        extra={"monthly_views": u.monthly_views} if u.monthly_views is not None else {},
    )
