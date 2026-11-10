"""
YouTube Data API v3 client — raw HTTP calls only, no business logic.

Auth is via an API key query parameter (public data) and/or an OAuth2
bearer token (required for `mine=true` channel access).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ProviderError
from bapp_connectors.core.ids import plain_id

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Resumable upload endpoint (videos.insert) — outside the Data API base URL,
# passed as an absolute URL (the shared http client accepts those).
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def youtube_id(value: str, what: str) -> str:
    """A channel/playlist/video id: letters, digits, ``_`` and ``-`` only."""
    return plain_id(value, what)


def with_cursor(page: dict) -> dict:
    """A Data API list page with ``nextPageToken``/``prevPageToken`` renamed ``next_cursor``/``prev_cursor``.

    Kept for one uniform ``next_cursor`` key across the AI reads (App Store, Google Play,
    YouTube). BAPP no longer redacts exact page-token keys such as ``nextPageToken``, so the
    rename is not needed for the agent to see the cursor.
    """
    out = {k: v for k, v in page.items() if k not in ("nextPageToken", "prevPageToken")}
    out["next_cursor"] = page.get("nextPageToken")
    out["prev_cursor"] = page.get("prevPageToken")
    return out


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

    def _auth_headers(self) -> dict | None:
        """Bearer-token headers when an OAuth access token is configured."""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return None

    def _get(self, path: str, **params) -> dict:
        """GET a Data API resource, adding the API key and/or bearer token."""
        query = {k: v for k, v in params.items() if v is not None}
        if self.api_key:
            query["key"] = self.api_key
        return self.http.call("GET", path, headers=self._auth_headers(), params=query)

    # ── Channels ──

    @ai_method(
        "read",
        "A YouTube channel (snippet, statistics, uploads playlist ID) by its ID, or the connected channel when omitted.",
    )
    def get_channel(self, channel_id: str | None = None) -> dict:
        """channels.list — fetch a channel by ID, or the authorized user's channel when omitted."""
        params: dict = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            params["id"] = youtube_id(channel_id, "channel_id")
        else:
            params["mine"] = "true"
        return self._get("channels", **params)

    # ── Playlist items (uploads) ──

    def list_playlist_items(self, playlist_id: str, max_results: int = 25, page_token: str | None = None) -> dict:
        """playlistItems.list — page through a playlist (typically the channel's uploads)."""
        return self._get(
            "playlistItems",
            part="snippet,contentDetails",
            playlistId=youtube_id(playlist_id, "playlist_id"),
            maxResults=max_results,
            pageToken=page_token,
        )

    # ── Videos ──

    @ai_method("read", "Up to 50 videos by their IDs: title, description, statistics, duration, privacy status.")
    def list_videos(self, video_ids: list[str]) -> dict:
        """videos.list — hydrate videos by ID with snippet, statistics, contentDetails, and status."""
        return self._get(
            "videos",
            part="snippet,statistics,contentDetails,status",
            id=",".join(youtube_id(v, "video_ids") for v in video_ids),
        )

    @ai_method(
        "read",
        "Page through a playlist's videos (e.g. the channel's uploads playlist from get_channel). "
        "Pass back next_cursor to get the next page.",
    )
    def list_playlist_videos(
        self, playlist_id: str, max_results: int = 25, cursor: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return with_cursor(self.list_playlist_items(playlist_id, max_results=max_results, page_token=cursor))

    # ── Comments ──

    @ai_method(
        "read",
        "List the top-level comment threads of a video, newest first, with their first replies. "
        "Pass back next_cursor to get the next page.",
    )
    def list_video_comments(
        self, video_id: str, max_results: int = 20, cursor: Annotated[str, "free_text"] | None = None
    ) -> dict:
        page = self._get(
            "commentThreads",
            part="snippet,replies",
            videoId=youtube_id(video_id, "video_id"),
            maxResults=max_results,
            order="time",
            textFormat="plainText",
            pageToken=cursor,
        )
        return with_cursor(page)

    # ── Upload (videos.insert, resumable) ──

    def upload_video_init(self, metadata: dict) -> str:
        """Start a resumable videos.insert session; return the upload session URL.

        POSTs the video metadata (snippet + status) and reads the session URL
        from the ``Location`` response header.
        """
        response = self.http.call(
            "POST",
            UPLOAD_URL,
            direct_response=True,
            headers=self._auth_headers(),
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata,
        )
        if not response.ok:
            raise ProviderError(
                f"YouTube resumable upload init failed: {response.status_code}",
                status_code=response.status_code,
            )
        location = response.headers.get("Location", "")
        if not location:
            raise ProviderError("YouTube resumable upload init returned no Location header")
        return location

    def upload_video_content(self, upload_url: str, content: bytes) -> dict:
        """PUT the video bytes to the resumable session URL; return the video resource."""
        headers = {"Content-Type": "video/*"}
        if auth_headers := self._auth_headers():
            headers.update(auth_headers)
        return self.http.call("PUT", upload_url, headers=headers, data=content)
