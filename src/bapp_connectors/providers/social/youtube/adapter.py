"""
YouTube Shorts social adapter — implements SocialPort.

Reads channel info, uploads (filtered to Shorts by default), and statistics
via the YouTube Data API v3.

Auth: API key query parameter (public data) and/or OAuth2 bearer token
(required for `mine=true` channel access).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.youtube.client import YouTubeApiClient
from bapp_connectors.providers.social.youtube.errors import first_item_or_not_found
from bapp_connectors.providers.social.youtube.manifest import manifest
from bapp_connectors.providers.social.youtube.mappers import (
    account_from_channel,
    account_stats_from_channel,
    post_from_video,
    stats_from_video,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.social import SocialAccount, SocialAccountStats, SocialPost, SocialPostStats


class YouTubeSocialAdapter(SocialPort):
    """
    YouTube Data API v3 adapter.

    Implements SocialPort over the connected channel's uploads playlist.
    With ``shorts_only`` (default), listings are filtered to videos not longer
    than ``shorts_max_seconds``.
    """

    manifest = manifest

    def __init__(
        self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs
    ):
        self.credentials = credentials
        config = self.manifest.settings.apply_defaults(config or {})
        self._channel_id: str = config.get("channel_id") or ""
        self._shorts_only = str(config.get("shorts_only", "true")).lower() in ("true", "1", "yes")
        self._shorts_max_seconds = int(config.get("shorts_max_seconds", 180))
        self._uploads_playlist_id: str = ""

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=self.manifest.base_url,
                auth=NoAuth(),
                provider_name="youtube",
            )

        self.client = YouTubeApiClient(
            http_client=http_client,
            api_key=credentials.get("api_key", ""),
            access_token=credentials.get("access_token", ""),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        if missing:
            return False
        api_key = self.credentials.get("api_key")
        access_token = self.credentials.get("access_token")
        if not api_key and not access_token:
            return False
        # An API key alone cannot resolve `mine=true` — a channel_id setting is required.
        if not access_token and not self._channel_id:
            return False
        return True

    def test_connection(self) -> ConnectionTestResult:
        try:
            channel = self._fetch_channel()
            title = channel.get("snippet", {}).get("title", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to YouTube channel '{title}'",
                details={"channel_id": channel.get("id", ""), "title": title},
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        return account_from_channel(self._fetch_channel())

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        playlist_id = self._resolve_uploads_playlist_id()
        page = self.client.list_playlist_items(playlist_id, max_results=limit, page_token=cursor)
        next_cursor = page.get("nextPageToken")

        video_ids = [item.get("contentDetails", {}).get("videoId", "") for item in page.get("items", [])]
        video_ids = [vid for vid in video_ids if vid]

        posts: list[SocialPost] = []
        if video_ids:
            videos = self.client.list_videos(video_ids).get("items", [])
            posts = [post_from_video(video, self._shorts_max_seconds) for video in videos]
            if self._shorts_only:
                posts = [
                    p
                    for p in posts
                    if p.duration_seconds is not None and p.duration_seconds <= self._shorts_max_seconds
                ]

        return PaginatedResult(items=posts, cursor=next_cursor, has_more=bool(next_cursor))

    def get_post(self, post_id: str) -> SocialPost:
        response = self.client.list_videos([post_id])
        video = first_item_or_not_found(response.get("items"), "video", post_id)
        return post_from_video(video, self._shorts_max_seconds)

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        response = self.client.list_videos([post_id])
        video = first_item_or_not_found(response.get("items"), "video", post_id)
        return stats_from_video(video)

    def get_account_stats(self, since: datetime | None = None, until: datetime | None = None) -> SocialAccountStats:
        """Fetch lifetime channel counters (subscribers, videos, total views).

        ``since``/``until`` are ignored — the Data API exposes no period-scoped
        statistics (that would require the YouTube Analytics API).
        """
        return account_stats_from_channel(self._fetch_channel())

    # ── Internal ──

    def _fetch_channel(self) -> dict:
        """Fetch the configured channel (by ID, or `mine=true` when only OAuth is set)."""
        response = self.client.get_channel(self._channel_id or None)
        return first_item_or_not_found(response.get("items"), "channel", self._channel_id or "mine")

    def _resolve_uploads_playlist_id(self) -> str:
        """Resolve and cache the channel's uploads playlist ID."""
        if not self._uploads_playlist_id:
            account = self.get_account()
            playlist_id = account.extra.get("uploads_playlist_id", "")
            if not playlist_id:
                raise PermanentProviderError(f"YouTube channel {account.id} has no uploads playlist")
            self._uploads_playlist_id = playlist_id
        return self._uploads_playlist_id
