"""
YouTube Data API v3 client — raw HTTP calls only, no business logic.

Auth is via an API key query parameter (public data) and/or an OAuth2
bearer token (required for `mine=true` channel access).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


class YouTubeApiClient:
    """
    Low-level YouTube Data API v3 client.

    This class only handles HTTP calls and response parsing.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, api_key: str = "", access_token: str = ""):
        self.http = http_client
        self.api_key = api_key
        self.access_token = access_token

    def _get(self, path: str, **params) -> dict:
        """GET a Data API resource, adding the API key and/or bearer token."""
        query = {k: v for k, v in params.items() if v is not None}
        if self.api_key:
            query["key"] = self.api_key
        headers = None
        if self.access_token:
            headers = {"Authorization": f"Bearer {self.access_token}"}
        return self.http.call("GET", path, headers=headers, params=query)

    # ── Channels ──

    def get_channel(self, channel_id: str | None = None) -> dict:
        """channels.list — fetch a channel by ID, or the authorized user's channel when omitted."""
        params: dict = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            params["id"] = channel_id
        else:
            params["mine"] = "true"
        return self._get("channels", **params)

    # ── Playlist items (uploads) ──

    def list_playlist_items(self, playlist_id: str, max_results: int = 25, page_token: str | None = None) -> dict:
        """playlistItems.list — page through a playlist (typically the channel's uploads)."""
        return self._get(
            "playlistItems",
            part="snippet,contentDetails",
            playlistId=playlist_id,
            maxResults=max_results,
            pageToken=page_token,
        )

    # ── Videos ──

    def list_videos(self, video_ids: list[str]) -> dict:
        """videos.list — hydrate videos by ID with snippet, statistics, and contentDetails."""
        return self._get(
            "videos",
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids),
        )
