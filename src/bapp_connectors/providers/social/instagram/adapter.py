"""
Instagram social adapter — implements SocialPort + SocialPublishCapability.

Covers an Instagram *Business/Creator* account via the Instagram Graph API
(graph.facebook.com v19.0): profile, published media (incl. Reels), per-media
stats, account-level insights, and URL-based publishing (images and Reels).

Auth: Page/user access token with instagram scopes, sent as a Bearer header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from bapp_connectors.core.capabilities import OAuthCapability, SocialPublishCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.social import (
    PublishResult,
    PublishStatus,
    SocialMediaType,
    SocialPrivacy,
)
from bapp_connectors.core.errors import ConnectorError, ValidationError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.instagram.client import InstagramGraphClient
from bapp_connectors.providers.social.instagram.errors import check_payload
from bapp_connectors.providers.social.instagram.manifest import manifest
from bapp_connectors.providers.social.instagram.mappers import (
    account_from_ig,
    account_stats_from_ig,
    insights_to_dict,
    insights_to_totals,
    post_from_ig,
    post_stats_from_ig,
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

MEDIA_INSIGHT_METRICS = "impressions,reach,saved"
VIDEO_INSIGHT_METRICS = "plays,video_views"
ACCOUNT_INSIGHT_METRICS = "impressions,reach"

_FB_OAUTH_DIALOG_URL = "https://www.facebook.com/v19.0/dialog/oauth"


class InstagramSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    Instagram Business/Creator account adapter (Instagram Graph API v19.0).

    Implements SocialPort for a single IG Business account: account profile,
    media listing (incl. Reels), per-media stats via media insights, and
    account stats via daily account insights. Insights calls degrade
    gracefully — when the token lacks ``instagram_manage_insights`` the
    engagement counters embedded in media objects are still returned.

    Implements SocialPublishCapability: Instagram content publishing is
    URL-based — Meta fetches the media from a public ``draft.media_url``
    (local ``file_path``/``content`` uploads are rejected, and Instagram has
    no text-only posts). Images publish synchronously via the two-step
    container -> media_publish flow; videos/Reels come back PROCESSING while
    Meta transcodes — poll ``check_publish_status`` with the returned
    ``publish_id`` (the container id): it performs the final media_publish
    step once the container reaches FINISHED.

    Implements OAuthCapability: Meta OAuth2 authorization code flow. The
    exchanged token is a *user* token — call ``list_instagram_accounts`` with
    it to find the Page-backed IG account and its Page access token, then
    store the Page token as the ``token`` credential and the IG account id as
    ``ig_user_id``.
    """

    manifest = manifest

    ACCOUNT_FIELDS = "id,username,name,biography,profile_picture_url,followers_count,follows_count,media_count,website"
    MEDIA_FIELDS = (
        "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,"
        "timestamp,like_count,comments_count"
    )

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        self.ig_user_id = credentials.get("ig_user_id", "")
        self._app_id = credentials.get("app_id", "")
        self._app_secret = credentials.get("app_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="instagram",
            )

        self.client = InstagramGraphClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self._app_id and self._app_secret:
            # OAuth-flow-only adapter: app credentials alone are enough to run the flow.
            return True
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0 and bool(self.credentials.get("token"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            user = self.client.get_object(self.ig_user_id, self.ACCOUNT_FIELDS)
            username = user.get("username", self.ig_user_id)
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Instagram account '@{username}'",
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
            "state": state,
            "scope": ",".join(scopes),
        }
        return f"{_FB_OAUTH_DIALOG_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        """Exchange the authorization code for a short-lived *user* access token.

        The returned token is not the token to store yet — pass it to
        ``list_instagram_accounts`` to pick the Page access token (and the
        ``ig_user_id``) to store as credentials.
        """
        response = self.client.http.call(
            "GET",
            "oauth/access_token",
            params={
                "client_id": self._app_id,
                "redirect_uri": redirect_uri,
                "client_secret": self._app_secret,
                "code": code,
            },
        )
        data = check_payload(response if isinstance(response, dict) else {})
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Meta issues no refresh tokens
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Exchange the CURRENT ACCESS TOKEN for a long-lived one (~60 days).

        Meta has no refresh tokens — its "refresh" equivalent is the
        ``fb_exchange_token`` grant, which trades a valid (short- or long-lived)
        access token for a fresh long-lived token. Therefore ``refresh_token``
        here must be the current access token, and the returned
        ``OAuthTokens.refresh_token`` is always ``""``.
        """
        response = self.client.http.call(
            "GET",
            "oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "fb_exchange_token": refresh_token,
            },
        )
        data = check_payload(response if isinstance(response, dict) else {})
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token="",  # Meta issues no refresh tokens
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "app_id": self._app_id,
                    "app_secret": self._app_secret,
                },
            },
        )

    def list_instagram_accounts(self, user_token: str) -> list[dict]:
        """List the user's Pages that have a linked Instagram Business account.

        Helper for completing the OAuth flow (not part of OAuthCapability):
        the token returned by ``exchange_code_for_token``/``refresh_token`` is a
        *user* token, but this adapter authenticates against an IG Business
        account through its Facebook Page. Call this with the user token, pick
        the entry for your account, and store its ``page_token`` as the
        ``token`` credential and its ``ig_user_id`` as the ``ig_user_id``
        credential.

        Returns a list of ``{"page_id", "page_name", "page_token", "ig_user_id"}``
        dicts — Pages without a linked Instagram Business account are omitted.
        """
        response = self.client.http.call(
            "GET",
            "me/accounts",
            params={"access_token": user_token, "fields": "id,name,access_token,instagram_business_account"},
        )
        payload = check_payload(response if isinstance(response, dict) else {})
        return [
            {
                "page_id": page.get("id", ""),
                "page_name": page.get("name", ""),
                "page_token": page.get("access_token", ""),
                "ig_user_id": (page.get("instagram_business_account") or {}).get("id", ""),
            }
            for page in payload.get("data", [])
            if page.get("instagram_business_account")
        ]

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the connected IG Business account's profile."""
        user = self.client.get_object(self.ig_user_id, self.ACCOUNT_FIELDS)
        return account_from_ig(user)

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the account's published media (incl. Reels), newest first."""
        payload = self.client.get_edge(self.ig_user_id, "media", fields=self.MEDIA_FIELDS, limit=limit, after=cursor)
        paging = payload.get("paging", {})
        return PaginatedResult(
            items=[post_from_ig(media) for media in payload.get("data", [])],
            cursor=paging.get("cursors", {}).get("after"),
            has_more="next" in paging,
        )

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single media object by its IG media ID."""
        media = self.client.get_object(post_id, self.MEDIA_FIELDS)
        return post_from_ig(media)

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal stats for a media object: embedded engagement + media insights.

        Insights failures are tolerated (missing ``instagram_manage_insights``
        permission, media types without insights) so plain engagement counters
        still come through. Video view metrics (``plays``/``video_views``) are
        requested in a separate tolerated call — the Graph API rejects the
        whole request when a metric is invalid for the media type.
        """
        media = self.client.get_object(post_id, self.MEDIA_FIELDS)

        insights = None
        try:
            insights = insights_to_dict(self.client.get_insights(post_id, MEDIA_INSIGHT_METRICS))
        except ConnectorError:
            insights = None

        if media.get("media_type") == "VIDEO":
            try:
                video_insights = insights_to_dict(self.client.get_insights(post_id, VIDEO_INSIGHT_METRICS))
                insights = {**(insights or {}), **video_insights}
            except ConnectorError:
                pass

        stats = post_stats_from_ig(media, insights)
        if stats.post_id != post_id:
            stats = stats.model_copy(update={"post_id": post_id})
        return stats

    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch account-level stats: followers + daily impressions/reach summed over the period.

        Insights failures are tolerated so lifetime counters (followers,
        media_count) still come through when the token lacks
        ``instagram_manage_insights``.
        """
        user = self.client.get_object(self.ig_user_id, self.ACCOUNT_FIELDS)

        insights = None
        try:
            payload = self.client.get_insights(
                self.ig_user_id,
                ACCOUNT_INSIGHT_METRICS,
                period="day",
                since=int(since.timestamp()) if since else None,
                until=int(until.timestamp()) if until else None,
            )
            insights = insights_to_totals(payload)
        except ConnectorError:
            insights = None

        stats = account_stats_from_ig(user, insights)
        return stats.model_copy(update={"period_start": since, "period_end": until})

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish an image or video/Reel to the IG Business account.

        Instagram content publishing is URL-based: Meta fetches the media from
        a public ``draft.media_url`` — local ``file_path``/``content`` uploads
        are rejected, and text-only posts do not exist on Instagram. Images
        publish synchronously (container + media_publish); videos are always
        published as Reels and come back PROCESSING while Meta transcodes —
        poll ``check_publish_status`` with the returned ``publish_id``.
        """
        if draft.privacy != SocialPrivacy.PUBLIC:
            raise ValidationError("Instagram Business accounts publish publicly only")
        if draft.file_path or draft.content is not None:
            raise ValidationError(
                "Instagram publishing is URL-based: Meta fetches the media from a public URL — "
                "host the file and pass it as draft.media_url (file_path/content uploads are not supported)"
            )
        if not draft.media_url:
            raise ValidationError("Instagram has no text-only posts; a media_url (image or video) is required")

        if draft.media_type == SocialMediaType.IMAGE:
            return self._publish_image(draft)
        if draft.media_type in (SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO):
            return self._publish_video(draft)
        raise ValidationError(f"Instagram cannot publish media of type '{draft.media_type}'")

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll an asynchronous video/Reel publish by its media container id.

        This performs the *final publish step*: once Meta finishes transcoding
        (container status FINISHED) the container is published via
        media_publish and the resulting media id is returned as ``post_id``.
        """
        container = self.client.get_object(publish_id, "status_code,status")

        status_code = container.get("status_code", "")
        if status_code == "FINISHED":
            response = self.client.post_edge(self.ig_user_id, "media_publish", {"creation_id": publish_id})
            return PublishResult(
                post_id=str(response.get("id", "")),
                publish_id=publish_id,
                status=PublishStatus.PUBLISHED,
                extra=response,
            )
        if status_code == "PUBLISHED":
            return PublishResult(publish_id=publish_id, status=PublishStatus.PUBLISHED)
        if status_code in ("ERROR", "EXPIRED"):
            error = container.get("status", "") or f"Instagram media container {publish_id} failed ({status_code})"
            return PublishResult(publish_id=publish_id, status=PublishStatus.FAILED, error=error)
        return PublishResult(publish_id=publish_id, status=PublishStatus.PROCESSING)

    def _publish_image(self, draft: SocialPostDraft) -> PublishResult:
        """POST {ig_user_id}/media + media_publish — images publish synchronously."""
        payload = {"image_url": draft.media_url, "caption": draft.description, **draft.extra}
        container = self.client.post_edge(self.ig_user_id, "media", payload)
        creation_id = str(container.get("id", ""))

        response = self.client.post_edge(self.ig_user_id, "media_publish", {"creation_id": creation_id})
        return PublishResult(
            post_id=str(response.get("id", "")),
            publish_id=creation_id,
            status=PublishStatus.PUBLISHED,
            extra=response,
        )

    def _publish_video(self, draft: SocialPostDraft) -> PublishResult:
        """POST {ig_user_id}/media (REELS container) — Meta transcodes asynchronously."""
        payload = {
            "media_type": "REELS",
            "video_url": draft.media_url,
            "caption": draft.description,
            **draft.extra,
        }
        container = self.client.post_edge(self.ig_user_id, "media", payload)
        return PublishResult(
            post_id="",
            publish_id=str(container.get("id", "")),
            status=PublishStatus.PROCESSING,
            extra=container,
        )
