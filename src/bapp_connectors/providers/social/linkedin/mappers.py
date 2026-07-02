"""
LinkedIn REST API <-> DTO mappers.

Converts raw LinkedIn payloads for an organization page (organization object,
posts finder, share statistics) into the normalized social DTOs. Metrics
LinkedIn does not return are left as ``None`` per the universal stats
interface; LinkedIn tracks video views separately from impressions, so
``views`` stays ``None`` here.
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
    SocialPostDraft,
    SocialPostStats,
)

_HASHTAG_RE = re.compile(r"#(\w+)")


def org_urn(org_id: str) -> str:
    """Build the organization URN from its numeric ID."""
    return f"urn:li:organization:{org_id}"


def _feed_update_url(post_urn: str) -> str:
    """Public feed URL of a post URN."""
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


# ── Account ──


def account_from_org(org: dict, follower_count: int | None) -> SocialAccount:
    """Map an organization object (+ networkSizes follower count) to a SocialAccount."""
    vanity_name = org.get("vanityName", "") or ""
    return SocialAccount(
        id=str(org.get("id", "")),
        username=vanity_name,
        display_name=org.get("localizedName", "") or "",
        profile_url=f"https://www.linkedin.com/company/{vanity_name}/" if vanity_name else "",
        description=org.get("localizedDescription", "") or "",
        followers_count=follower_count,
        provider_meta=ProviderMeta(
            provider="linkedin",
            raw_id=str(org.get("id", "")),
            raw_payload=org,
            fetched_at=datetime.now(UTC),
        ),
    )


# ── Posts ──


def post_from_linkedin(post: dict) -> SocialPost:
    """Map a LinkedIn post object (posts finder item) to a SocialPost."""
    post_urn = str(post.get("id", ""))
    commentary = post.get("commentary", "") or ""
    author = post.get("author", "") or ""

    published_at = None
    if created_at := post.get("createdAt"):
        published_at = datetime.fromtimestamp(created_at / 1000, tz=UTC)

    media_type, extra = _media_type_from_post(post)

    return SocialPost(
        id=post_urn,
        account_id=author.rsplit(":", 1)[-1] if author else "",
        url=_feed_update_url(post_urn),
        description=commentary,
        media_type=media_type,
        published_at=published_at,
        hashtags=_HASHTAG_RE.findall(commentary),
        extra=extra,
        provider_meta=ProviderMeta(
            provider="linkedin",
            raw_id=post_urn,
            raw_payload=post,
            fetched_at=datetime.now(UTC),
        ),
    )


def _media_type_from_post(post: dict) -> tuple[SocialMediaType, dict]:
    """Derive (SocialMediaType, extra) from the post's ``content`` object.

    ``content.media`` carries a typed URN (``urn:li:video:...`` /
    ``urn:li:image:...``); ``content.article`` is a link post, normalized to
    TEXT with the link preserved in ``extra["article_url"]``; no content at
    all is a plain TEXT post.
    """
    content = post.get("content") or {}
    if media := content.get("media"):
        media_urn = str(media.get("id", ""))
        if ":video:" in media_urn:
            return SocialMediaType.VIDEO, {}
        if ":image:" in media_urn:
            return SocialMediaType.IMAGE, {}
        return SocialMediaType.OTHER, {}
    if article := content.get("article"):
        return SocialMediaType.TEXT, {"article_url": article.get("source", "")}
    return SocialMediaType.TEXT, {}


# ── Stats ──


def stats_from_share_stats(stats: dict, post_id: str = "") -> SocialPostStats:
    """Map an organizationalEntityShareStatistics element to SocialPostStats.

    LinkedIn reports video views separately from impressions — ``views``
    stays ``None`` here.
    """
    totals = stats.get("totalShareStatistics") or {}
    return SocialPostStats(
        post_id=post_id or str(stats.get("share", "")),
        views=None,
        likes=totals.get("likeCount"),
        comments=totals.get("commentCount"),
        shares=totals.get("shareCount"),
        impressions=totals.get("impressionCount"),
        clicks=totals.get("clickCount"),
        engagement_rate=totals.get("engagement"),
        fetched_at=datetime.now(UTC),
    )


def account_stats_from(follower_count: int | None, share_stats: dict) -> SocialAccountStats:
    """Map the follower count + org-level share statistics to SocialAccountStats.

    Aggregate interaction counters have no universal account-level fields —
    they are preserved in ``extra``.
    """
    totals = share_stats.get("totalShareStatistics") or {}
    return SocialAccountStats(
        account_id=str(share_stats.get("organizationalEntity", "")).rsplit(":", 1)[-1],
        followers_count=follower_count,
        impressions=totals.get("impressionCount"),
        engagement_rate=totals.get("engagement"),
        fetched_at=datetime.now(UTC),
        extra={
            key: totals[source]
            for key, source in (
                ("likes", "likeCount"),
                ("comments", "commentCount"),
                ("shares", "shareCount"),
                ("clicks", "clickCount"),
            )
            if source in totals
        },
    )


# ── Publishing ──


def draft_to_post_payload(draft: SocialPostDraft, author_urn: str) -> dict:
    """Map a SocialPostDraft to a LinkedIn ``posts`` create payload.

    Text posts carry the message in ``commentary``; when ``draft.link`` is
    set the post becomes an article share (``content.article``).
    """
    payload = {
        "author": author_urn,
        "commentary": draft.description or draft.title,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if draft.link:
        payload["content"] = {"article": {"source": draft.link, "title": draft.title or draft.link}}
    return payload
