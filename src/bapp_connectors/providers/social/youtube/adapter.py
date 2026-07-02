"""
YouTube Shorts social adapter — implements SocialPort + SocialPublishCapability.

Reads channel info, uploads (filtered to Shorts by default), and statistics
via the YouTube Data API v3, and publishes videos via the resumable
videos.insert flow.

Auth: API key query parameter (public data) and/or OAuth2 bearer token
(required for `mine=true` channel access and for publishing).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import PublishResult, PublishStatus, SocialMediaType
from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.youtube.client import YouTubeApiClient
from bapp_connectors.providers.social.youtube.errors import first_item_or_not_found
from bapp_connectors.providers.social.youtube.manifest import manifest
from bapp_connectors.providers.social.youtube.mappers import (
    account_from_channel,
    account_stats_from_channel,
    draft_to_video_metadata,
    post_from_video,
    publish_result_from_video,
    stats_from_video,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostDraft,
        SocialPostStats,
    )

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
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
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
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
        # client_id + client_secret alone are enough to run the OAuth flow.
        if not api_key and not access_token:
            return bool(self._client_id and self._client_secret)
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

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        refresh_tok = data.get("refresh_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_tok,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "access_token": access_token,
                    "refresh_token": refresh_tok,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

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

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Upload a video via the resumable videos.insert flow.

        Requires an OAuth2 access token with the
        https://www.googleapis.com/auth/youtube.upload scope — an API key
        alone cannot upload. A video not longer than 3 minutes with a
        vertical or square aspect ratio becomes a Short automatically;
        there is no separate Shorts endpoint.
        """
        if not self.credentials.get("access_token"):
            raise AuthenticationError(
                "YouTube upload requires an OAuth2 access_token credential; an API key cannot publish"
            )
        if draft.media_type not in (SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO):
            raise ValidationError(f"YouTube can only publish videos, got media_type '{draft.media_type}'")
        content = self._resolve_draft_content(draft)
        upload_url = self.client.upload_video_init(draft_to_video_metadata(draft))
        video = self.client.upload_video_content(upload_url, content)
        return publish_result_from_video(video)

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll a video's processing state; ``publish_id`` is the video ID.

        Maps ``status.uploadStatus``: "failed"/"rejected" → FAILED (error from
        failureReason/rejectionReason), "processed" → PUBLISHED, anything else
        ("uploaded", ...) → PROCESSING. Raises PermanentProviderError when the
        video ID does not exist.
        """
        response = self.client.list_videos([publish_id])
        video = first_item_or_not_found(response.get("items"), "video", publish_id)
        status = video.get("status", {})
        upload_status = status.get("uploadStatus", "")

        if upload_status in ("failed", "rejected"):
            publish_status = PublishStatus.FAILED
            error = status.get("failureReason") or status.get("rejectionReason") or upload_status
        elif upload_status == "processed":
            publish_status = PublishStatus.PUBLISHED
            error = ""
        else:
            publish_status = PublishStatus.PROCESSING
            error = ""

        return PublishResult(
            post_id=publish_id,
            publish_id=publish_id,
            status=publish_status,
            url=f"https://www.youtube.com/watch?v={publish_id}",
            error=error,
            extra={"upload_status": upload_status},
        )

    # ── Internal ──

    def _resolve_draft_content(self, draft: SocialPostDraft) -> bytes:
        """Resolve the draft's video bytes from ``content`` or ``file_path``."""
        if draft.content is not None:
            return draft.content
        if draft.file_path:
            return Path(draft.file_path).read_bytes()
        raise ValidationError(
            "YouTube requires the video bytes via draft.content or draft.file_path; "
            "media_url is not supported (YouTube does not fetch remote media)"
        )

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
