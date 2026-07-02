"""
TikTok Display API v2 client — raw HTTP calls only, no business logic.

Auth is a Bearer user access token applied by the HTTP client. Every response
is unwrapped through :func:`check_response`, which raises framework errors
for non-"ok" error codes in the TikTok envelope.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bapp_connectors.providers.social.tiktok.errors import check_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

USER_FIELDS = ",".join((
    "open_id",
    "union_id",
    "avatar_url",
    "display_name",
    "username",
    "bio_description",
    "profile_deep_link",
    "is_verified",
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
))

VIDEO_FIELDS = ",".join((
    "id",
    "title",
    "video_description",
    "create_time",
    "cover_image_url",
    "share_url",
    "duration",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "embed_link",
))


class TikTokApiClient:
    """
    Low-level TikTok Display API v2 client.

    This class only handles HTTP calls and envelope unwrapping.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient):
        self.http = http_client

    def get_user_info(self) -> dict:
        """GET user/info/ — returns the ``data`` object containing ``user``."""
        response = self.http.call("GET", "user/info/", params={"fields": USER_FIELDS})
        return check_response(response)

    def list_videos(self, cursor: int | None = None, max_count: int = 20) -> dict:
        """POST video/list/ — returns ``data`` with ``videos``, ``cursor``, ``has_more``."""
        body: dict = {"max_count": max_count}
        if cursor is not None:
            body["cursor"] = cursor
        response = self.http.call("POST", "video/list/", params={"fields": VIDEO_FIELDS}, json=body)
        return check_response(response)

    def query_videos(self, video_ids: list[str]) -> dict:
        """POST video/query/ — returns ``data`` with ``videos`` for the given IDs."""
        body = {"filters": {"video_ids": video_ids}}
        response = self.http.call("POST", "video/query/", params={"fields": VIDEO_FIELDS}, json=body)
        return check_response(response)
