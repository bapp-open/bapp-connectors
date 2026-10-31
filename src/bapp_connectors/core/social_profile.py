"""
Fit a SocialPostDraft to what a channel accepts (its SocialPublishProfile).

Optional extras the channel cannot carry (hashtags over the limit, mentions,
product tags, location, title) are dropped and reported in ``omitted``. Things
that cannot be fixed by dropping data (wrong format/media, text too long,
missing title, video duration) are reported in ``errors`` and left unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto.social import SocialFormatProfile, SocialPostDraft, SocialPublishProfile


@dataclass(frozen=True)
class FittedDraft:
    draft: SocialPostDraft
    omitted: list[str]
    errors: list[str]


def _normalize_hashtags(hashtags: list[str]) -> list[str]:
    """Strip whitespace and leading '#', drop empties, dedupe case-insensitively (first spelling wins)."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in hashtags:
        tag = tag.strip().lstrip("#").strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def compose_caption(text: str, hashtags: list[str]) -> str:
    """Caption as published: the text, a blank line, then the hashtags."""
    tags = " ".join(f"#{t}" for t in _normalize_hashtags(hashtags))
    text = text.strip()
    if text and tags:
        return f"{text}\n\n{tags}"
    return text or tags


def _location_supported(draft: SocialPostDraft, fmt: SocialFormatProfile) -> bool:
    """The format takes a location, and — when the draft carries media — for this media type."""
    if not fmt.supports_location:
        return False
    has_media = bool(draft.media_url or draft.file_path or draft.content is not None)
    return fmt.location_media_types is None or not has_media or draft.media_type in fmt.location_media_types


def fit_draft(
    draft: SocialPostDraft,
    profile: SocialPublishProfile,
    video_seconds: float | None = None,
) -> FittedDraft:
    fmt = profile.for_format(draft.format)
    if fmt is None:
        return FittedDraft(draft=draft, omitted=[], errors=["format_unsupported"])

    omitted: list[str] = []
    errors: list[str] = []
    update: dict = {}

    if draft.media_type not in fmt.media_types:
        errors.append("media_type_unsupported")

    hashtags = draft.hashtags
    if fmt.max_hashtags is not None:
        unique = _normalize_hashtags(hashtags)
        if len(unique) > fmt.max_hashtags:
            hashtags = unique[: fmt.max_hashtags]
            update["hashtags"] = hashtags
            omitted.append("hashtags")

    if draft.mentions:
        limit = (
            (fmt.max_mentions if fmt.max_mentions is not None else len(draft.mentions)) if fmt.supports_mentions else 0
        )
        if len(draft.mentions) > limit:
            update["mentions"] = draft.mentions[:limit]
            omitted.append("mentions")

    if draft.product_tags and not fmt.supports_product_tags:
        update["product_tags"] = []
        omitted.append("product_tags")

    if draft.location is not None and not _location_supported(draft, fmt):
        update["location"] = None
        omitted.append("location")

    if fmt.max_title_length == 0:
        if draft.title:
            update["title"] = ""
            omitted.append("title")
    else:
        if fmt.requires_title and not draft.title.strip():
            errors.append("title_required")
        if fmt.max_title_length is not None and len(draft.title) > fmt.max_title_length:
            errors.append("title_too_long")

    if fmt.max_text_length is not None and len(compose_caption(draft.description, hashtags)) > fmt.max_text_length:
        errors.append("text_too_long")

    if video_seconds is not None:
        if fmt.min_video_seconds is not None and video_seconds < fmt.min_video_seconds:
            errors.append("video_too_short")
        if fmt.max_video_seconds is not None and video_seconds > fmt.max_video_seconds:
            errors.append("video_too_long")

    fitted = draft.model_copy(update=update) if update else draft
    return FittedDraft(draft=fitted, omitted=omitted, errors=errors)
