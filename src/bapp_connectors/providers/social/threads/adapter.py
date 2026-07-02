"""
Threads social adapter — implements SocialPort + SocialPublishCapability + OAuthCapability.

Covers the connected Threads profile via the Threads API: profile, published
threads with cursor pagination, media/user insights (the universal stats
interface), and publishing (text, image, video posts).

Auth: Threads user access token sent as a Bearer header; the API addresses
the token owner as "me", so no user ID credential is needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import PublishResult, PublishStatus, SocialMediaType
from bapp_connectors.core.errors import ConnectorError, ValidationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.threads.client import ThreadsApiClient
from bapp_connectors.providers.social.threads.errors import check_payload
from bapp_connectors.providers.social.threads.manifest import manifest
from bapp_connectors.providers.social.threads.mappers import (
    account_from_threads,
    account_stats_from_insights,
    insights_to_dict,
    post_from_threads,
    post_stats_from_insights,
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

MEDIA_INSIGHT_METRICS = "views,likes,replies,reposts,quotes,shares"
USER_INSIGHT_METRICS = "views,likes,replies,reposts,quotes,followers_count"

# Threads OAuth lives on threads.net / graph.threads.net — NOT facebook.com.
_THREADS_AUTH_URL = "https://threads.net/oauth/authorize"
_THREADS_TOKEN_URL = "https://graph.threads.net/oauth/access_token"
_THREADS_LONG_LIVED_TOKEN_URL = "https://graph.threads.net/access_token"
_THREADS_REFRESH_TOKEN_URL = "https://graph.threads.net/refresh_access_token"

_DRAFT_TO_THREADS_MEDIA_TYPE = {
    SocialMediaType.TEXT: "TEXT",
    SocialMediaType.IMAGE: "IMAGE",
    SocialMediaType.VIDEO: "VIDEO",
    SocialMediaType.SHORT_VIDEO: "VIDEO",
}


class ThreadsSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    Threads API adapter (graph.threads.net v1.0).

    Implements SocialPort for the connected Threads profile: account profile
    (follower count filled from user insights, tolerated when the token lacks
    threads_manage_insights), threads listing with cursor pagination, per-post
    stats via media insights, and account stats via user insights.

    Implements SocialPublishCapability with the two-step container flow:
    a media container is created on me/threads, then published via
    me/threads_publish. Text and image posts publish immediately; videos come
    back PROCESSING while Meta transcodes — poll ``check_publish_status`` with
    the returned ``publish_id`` (the container id), which performs the final
    me/threads_publish call once the container is FINISHED.

    Implements OAuthCapability with the Threads-specific OAuth2 flow on
    threads.net (not facebook.com), including the long-lived token exchange
    and the th_refresh_token rolling refresh.
    """

    manifest = manifest

    USER_FIELDS = "id,username,name,threads_profile_picture_url,threads_biography"
    MEDIA_FIELDS = "id,text,media_type,media_url,permalink,timestamp,username,is_quote_post"

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        self._app_id = credentials.get("app_id", "")
        self._app_secret = credentials.get("app_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="threads",
            )

        self.client = ThreadsApiClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        # Either a ready-to-use access token, or the Meta app credentials
        # needed to obtain one via the OAuth flow.
        has_token = bool(self.credentials.get("token"))
        has_oauth_app = bool(self._app_id and self._app_secret)
        return has_token or has_oauth_app

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.get_object("me", self.USER_FIELDS)
            username = user.get("username") or user.get("id", "unknown")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Threads profile @{username}",
                details=user,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": state,
        }
        return f"{_THREADS_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        """Exchange the authorization code for a long-lived Threads access token.

        Two calls in one method: the code is first exchanged for a short-lived
        token (valid ~1 hour), which is immediately upgraded to a long-lived
        token (~60 days) via the ``th_exchange_token`` grant. The Threads user
        id from the short-lived exchange is surfaced in ``extra["user_id"]``.
        """
        response = self.client.http.call(
            "POST",
            _THREADS_TOKEN_URL,
            data={
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        short_lived = check_payload(response if isinstance(response, dict) else {})

        response = self.client.http.call(
            "GET",
            _THREADS_LONG_LIVED_TOKEN_URL,
            params={
                "grant_type": "th_exchange_token",
                "client_secret": self._app_secret,
                "access_token": short_lived.get("access_token", ""),
            },
        )
        long_lived = check_payload(response if isinstance(response, dict) else {})
        return self._tokens_from_response(long_lived, user_id=str(short_lived.get("user_id", "")))

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh a long-lived Threads access token before it expires.

        Threads has no refresh tokens — the ``th_refresh_token`` grant refreshes
        the access token itself, so the ``refresh_token`` argument here must be
        the CURRENT (unexpired, at least 24h old) long-lived access token, and
        the returned ``OAuthTokens.refresh_token`` is always ``""``.
        """
        response = self.client.http.call(
            "GET",
            _THREADS_REFRESH_TOKEN_URL,
            params={
                "grant_type": "th_refresh_token",
                "access_token": refresh_token,
            },
        )
        data = check_payload(response if isinstance(response, dict) else {})
        return self._tokens_from_response(data)

    def _tokens_from_response(self, data: dict, user_id: str = "") -> OAuthTokens:
        """Build OAuthTokens from a Threads token response ({access_token, token_type, expires_in})."""
        access_token = data.get("access_token", "")
        extra = {
            "credentials": {
                "token": access_token,
                "app_id": self._app_id,
                "app_secret": self._app_secret,
            },
        }
        if user_id:
            extra["user_id"] = user_id
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Threads issues no refresh tokens
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra=extra,
        )

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the connected profile; follower count comes from user insights.

        The profile object carries no follower count — it is fetched separately
        via the ``followers_count`` user insight. That call is tolerated
        (missing threads_manage_insights permission), leaving ``followers_count``
        as ``None``.
        """
        user = self.client.get_object("me", self.USER_FIELDS)
        account = account_from_threads(user)

        try:
            payload = self.client.get_insights("me", "followers_count", edge="threads_insights")
            followers = insights_to_dict(payload).get("followers_count")
        except ConnectorError:
            followers = None

        if followers is not None:
            account = account.model_copy(update={"followers_count": followers})
        return account

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the profile's threads, newest first, with cursor pagination."""
        payload = self.client.get_edge("me", "threads", fields=self.MEDIA_FIELDS, limit=limit, after=cursor)
        paging = payload.get("paging", {})
        return PaginatedResult(
            items=[post_from_threads(media) for media in payload.get("data", [])],
            cursor=paging.get("cursors", {}).get("after"),
            has_more="next" in paging,
        )

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single thread by its media ID."""
        media = self.client.get_object(post_id, self.MEDIA_FIELDS)
        return post_from_threads(media)

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal stats for a thread via media insights.

        Insights failures are tolerated (missing threads_manage_insights
        permission, media types without insights) — the stats come back with
        all metrics ``None``.
        """
        try:
            payload = self.client.get_insights(post_id, MEDIA_INSIGHT_METRICS)
        except ConnectorError:
            payload = None
        return post_stats_from_insights(post_id, payload)

    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch account-level stats via user insights (``me/threads_insights``).

        ``since``/``until`` scope the period metrics (views, likes, replies,
        reposts, quotes); ``followers_count`` is a lifetime total regardless
        of the period.
        """
        payload = self.client.get_insights(
            "me",
            USER_INSIGHT_METRICS,
            edge="threads_insights",
            since=int(since.timestamp()) if since else None,
            until=int(until.timestamp()) if until else None,
        )
        stats = account_stats_from_insights(payload)
        return stats.model_copy(update={"period_start": since, "period_end": until})

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish a text, image or video post via the two-step container flow.

        A media container is created on me/threads, then published via
        me/threads_publish. Text and image containers are ready immediately, so
        both steps run here and the result is PUBLISHED. Video containers need
        transcoding first — the result is PROCESSING with the container id as
        ``publish_id``; poll ``check_publish_status`` with it, which performs
        the final me/threads_publish call once the container is FINISHED.

        Threads fetches media from a public URL only — image/video drafts
        require ``media_url`` (file_path/content uploads are not supported).
        ``draft.extra`` is merged into the container parameters last (e.g.
        ``reply_control``, ``topic_tag``).
        """
        threads_media_type = _DRAFT_TO_THREADS_MEDIA_TYPE.get(draft.media_type)
        if threads_media_type is None:
            raise ValidationError(f"Threads cannot publish media of type '{draft.media_type}'")

        text = draft.description or draft.title
        params = {"media_type": threads_media_type}
        if text:
            params["text"] = text

        if threads_media_type == "TEXT":
            if not text:
                raise ValidationError("Threads text posts require a text (description/title)")
        else:
            if draft.file_path or draft.content is not None:
                raise ValidationError(
                    "Threads fetches media from a public URL only — provide media_url "
                    "(file_path/content uploads are not supported)"
                )
            if not draft.media_url:
                raise ValidationError("Threads image/video posts require a publicly accessible media_url")
            media_param = "image_url" if threads_media_type == "IMAGE" else "video_url"
            params[media_param] = draft.media_url

        params.update(draft.extra)
        response = self.client.post_edge("me", "threads", params)
        creation_id = str(response.get("id", ""))

        if threads_media_type == "VIDEO":
            return PublishResult(
                publish_id=creation_id,
                status=PublishStatus.PROCESSING,
                extra=response,
            )
        return self._publish_container(creation_id)

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll a video container and publish it once it is ready.

        Unlike synchronous platforms, the final publish call for videos
        happens HERE: when the container status reaches FINISHED, this method
        POSTs me/threads_publish and returns PUBLISHED with the post id.
        IN_PROGRESS containers stay PROCESSING; ERROR/EXPIRED containers are
        FAILED with the container's ``error_message``.
        """
        container = self.client.get_object(publish_id, "status,error_message")
        status = container.get("status", "")

        if status == "FINISHED":
            return self._publish_container(publish_id)
        if status in ("ERROR", "EXPIRED"):
            error = container.get("error_message") or f"Threads media container {publish_id} is {status}"
            return PublishResult(publish_id=publish_id, status=PublishStatus.FAILED, error=error)
        return PublishResult(publish_id=publish_id, status=PublishStatus.PROCESSING)

    def _publish_container(self, creation_id: str) -> PublishResult:
        """POST me/threads_publish — publish a ready media container."""
        response = self.client.post_edge("me", "threads_publish", {"creation_id": creation_id})
        return PublishResult(
            post_id=str(response.get("id", "")),
            publish_id=creation_id,
            status=PublishStatus.PUBLISHED,
            extra=response,
        )
