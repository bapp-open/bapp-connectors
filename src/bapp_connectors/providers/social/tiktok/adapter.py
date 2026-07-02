"""
TikTok Display API social adapter — implements SocialPort.

Exposes the connected TikTok account profile, its videos with cursor
pagination, and universal statistics via the TikTok Display API v2.

Auth: TikTok Login Kit OAuth user access token sent as a Bearer header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import PublishResult, PublishStatus, SocialMediaType
from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ValidationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.tiktok.client import TikTokApiClient
from bapp_connectors.providers.social.tiktok.manifest import manifest
from bapp_connectors.providers.social.tiktok.mappers import (
    account_from_tiktok,
    account_stats_from_tiktok,
    draft_to_post_info,
    post_from_tiktok,
    publish_result_from_status,
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

_TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


class TikTokSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    TikTok Display API v2 adapter.

    Implements SocialPort: account profile, video listing with cursor
    pagination, single-video lookup, and the universal stats interface.
    Implements SocialPublishCapability via the Content Posting API
    (direct post, PULL_FROM_URL only).
    Implements OAuthCapability via the Login Kit v2 authorization code
    flow with rotating refresh tokens.

    TikTok exposes lifetime counters only — account stats ignore the
    since/until period for filtering but pass it through in the result.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}
        self._client_key = credentials.get("client_key", "")
        self._client_secret = credentials.get("client_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(token=credentials.get("token", "")),
                provider_name="tiktok",
            )

        self.client = TikTokApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        if missing:
            return False
        # Either a ready-to-use access token, or the Login Kit app
        # credentials needed to obtain one via the OAuth flow.
        has_token = bool(self.credentials.get("token"))
        has_oauth_app = bool(self._client_key and self._client_secret)
        return has_token or has_oauth_app

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.get_user_info().get("user", {})
            display_name = user.get("display_name") or user.get("username") or "unknown"
            return ConnectionTestResult(
                success=True,
                message=f"Connected as {display_name}",
                details=user,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_key": self._client_key,
            "response_type": "code",
            "scope": ",".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{_TIKTOK_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _TIKTOK_TOKEN_URL,
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        return self._tokens_from_response(response)

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _TIKTOK_TOKEN_URL,
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        # TikTok rotates the refresh token on every refresh — the response
        # carries the new one, which _tokens_from_response picks up.
        return self._tokens_from_response(response)

    def _tokens_from_response(self, response: object) -> OAuthTokens:
        """Build OAuthTokens from TikTok's flat oauth/token/ response.

        Unlike the Display API, the token endpoint does not use the
        data/error envelope — errors come back flat as
        ``{"error": ..., "error_description": ...}``.
        """
        data = response if isinstance(response, dict) else {}
        if data.get("error"):
            raise AuthenticationError(
                f"TikTok OAuth error ({data['error']}): {data.get('error_description', '')}"
            )
        access_token = data.get("access_token", "")
        refresh_tok = data.get("refresh_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_tok,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "client_key": self._client_key,
                    "client_secret": self._client_secret,
                },
                "open_id": data.get("open_id", ""),
                "scope": data.get("scope", ""),
                "refresh_expires_in": data.get("refresh_expires_in"),
            },
        )

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the connected TikTok account profile."""
        data = self.client.get_user_info()
        return account_from_tiktok(data.get("user", {}))

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the account's videos, newest first, with cursor pagination.

        The cursor is TikTok's integer cursor, stringified for the framework.
        """
        tiktok_cursor = int(cursor) if cursor else None
        data = self.client.list_videos(cursor=tiktok_cursor, max_count=limit)
        items = [post_from_tiktok(video) for video in data.get("videos", [])]
        has_more = bool(data.get("has_more", False))
        next_cursor = str(data["cursor"]) if has_more and data.get("cursor") is not None else None
        return PaginatedResult(items=items, cursor=next_cursor, has_more=has_more)

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single video by ID via video/query/."""
        data = self.client.query_videos([post_id])
        videos = data.get("videos", [])
        if not videos:
            raise PermanentProviderError(f"TikTok video not found: {post_id}")
        return post_from_tiktok(videos[0])

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal statistics for a single video."""
        stats = self.get_post(post_id).stats
        assert stats is not None  # post_from_tiktok always embeds stats
        return stats

    def get_account_stats(self, since: datetime | None = None, until: datetime | None = None) -> SocialAccountStats:
        """Fetch universal account statistics.

        TikTok exposes lifetime counters only; the period does not filter
        anything but is passed through in the result.
        """
        data = self.client.get_user_info()
        stats = account_stats_from_tiktok(data.get("user", {}))
        return stats.model_copy(update={"period_start": since, "period_end": until})

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish a video via the Content Posting API (direct post).

        TikTok pulls the video from a public URL (PULL_FROM_URL); publishing
        is asynchronous — poll ``check_publish_status`` with the returned
        ``publish_id`` until PUBLISHED or FAILED.
        """
        if draft.media_type not in (SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO):
            raise ValidationError(
                f"TikTok direct post only supports videos, got media_type={draft.media_type}. "
                "Photo posts use a different endpoint and are not supported."
            )
        if not draft.media_url:
            raise ValidationError(
                "TikTok direct post requires a publicly accessible media_url "
                "(PULL_FROM_URL); chunked file upload from file_path/content "
                "is not supported yet."
            )
        source_info = {"source": "PULL_FROM_URL", "video_url": draft.media_url}
        data = self.client.publish_video_init(draft_to_post_info(draft), source_info)
        return PublishResult(
            publish_id=str(data.get("publish_id", "")),
            status=PublishStatus.PROCESSING,
            extra=data,
        )

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll a publish operation via post/publish/status/fetch/."""
        data = self.client.publish_status_fetch(publish_id)
        return publish_result_from_status(publish_id, data)
