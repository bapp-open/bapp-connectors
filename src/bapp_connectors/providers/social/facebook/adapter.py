"""
Facebook Page social adapter — implements SocialPort + SocialPublishCapability.

Covers a Facebook *Page* via the Graph API v19.0: page profile, published
posts (including Reels as they appear in the posts edge), per-post stats,
page-level insights, and publishing (feed posts, photos, videos).

Auth: Page access token sent as a Bearer header.
"""

from __future__ import annotations

from pathlib import Path
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
from bapp_connectors.providers.social.facebook.client import FacebookGraphClient
from bapp_connectors.providers.social.facebook.errors import check_payload
from bapp_connectors.providers.social.facebook.manifest import manifest
from bapp_connectors.providers.social.facebook.mappers import (
    account_from_page,
    account_stats_from_page,
    insights_to_dict,
    insights_to_totals,
    post_from_graph,
    post_stats_from_graph,
    publish_result_from_graph,
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

POST_INSIGHT_METRICS = "post_impressions,post_impressions_unique,post_clicks,post_video_views"
PAGE_INSIGHT_METRICS = "page_impressions,page_impressions_unique"

_FB_OAUTH_DIALOG_URL = "https://www.facebook.com/v19.0/dialog/oauth"


class FacebookSocialAdapter(SocialPort, SocialPublishCapability, OAuthCapability):
    """
    Facebook Page adapter (Graph API v19.0).

    Implements SocialPort for a single Facebook Page: account profile, posts
    listing (incl. Reels posts surfaced on the posts edge), per-post stats via
    post insights, and account stats via page insights. Insights calls degrade
    gracefully — when the token lacks ``read_insights`` the engagement counters
    embedded in post objects are still returned.

    Implements SocialPublishCapability: feed posts and photos publish
    synchronously; videos come back PROCESSING while Meta transcodes — poll
    ``check_publish_status`` with the returned ``publish_id``. Publishing
    requires the ``pages_manage_posts`` permission on the token.

    Implements OAuthCapability: Meta OAuth2 authorization code flow. The
    exchanged token is a *user* token — call ``list_page_tokens`` with it to
    obtain the Page access token to store as the ``token`` credential.
    """

    manifest = manifest

    PAGE_FIELDS = "id,name,username,link,about,followers_count,fan_count,picture{url},verification_status"
    POST_FIELDS = (
        "id,message,created_time,permalink_url,full_picture,attachments{media_type},"
        "shares,likes.summary(true),comments.summary(true)"
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
        self.page_id = credentials.get("page_id", "")
        self._app_id = credentials.get("app_id", "")
        self._app_secret = credentials.get("app_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="facebook",
            )

        self.client = FacebookGraphClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self._app_id and self._app_secret:
            # OAuth-flow-only adapter: app credentials alone are enough to run the flow.
            return True
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0 and bool(self.credentials.get("token"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            page = self.client.get_object(self.page_id, self.PAGE_FIELDS)
            page_name = page.get("name", self.page_id)
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Facebook Page '{page_name}'",
                details=page,
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

        The returned token is not a Page token — pass it to ``list_page_tokens``
        to pick the Page access token to store as the ``token`` credential.
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

    def list_page_tokens(self, user_token: str) -> list[dict]:
        """List the Pages the user manages, each with its Page access token.

        Helper for completing the OAuth flow (not part of OAuthCapability):
        the token returned by ``exchange_code_for_token``/``refresh_token`` is a
        *user* token, but this adapter authenticates with a *Page* token. Call
        this with the user token, pick the entry matching your ``page_id``, and
        store its ``access_token`` as the ``token`` credential.

        Returns a list of ``{"id", "name", "access_token"}`` dicts.
        """
        response = self.client.http.call(
            "GET",
            "me/accounts",
            params={"access_token": user_token, "fields": "id,name,access_token"},
        )
        payload = check_payload(response if isinstance(response, dict) else {})
        return [
            {
                "id": page.get("id", ""),
                "name": page.get("name", ""),
                "access_token": page.get("access_token", ""),
            }
            for page in payload.get("data", [])
        ]

    # ── SocialPort ──

    def get_account(self) -> SocialAccount:
        """Fetch the connected Page's profile."""
        page = self.client.get_object(self.page_id, self.PAGE_FIELDS)
        return account_from_page(page)

    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List the Page's published posts (incl. Reels posts), newest first."""
        payload = self.client.get_edge(self.page_id, "posts", fields=self.POST_FIELDS, limit=limit, after=cursor)
        paging = payload.get("paging", {})
        return PaginatedResult(
            items=[post_from_graph(post) for post in payload.get("data", [])],
            cursor=paging.get("cursors", {}).get("after"),
            has_more="next" in paging,
        )

    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single Page post by its Graph ID (``{page_id}_{post_id}``)."""
        post = self.client.get_object(post_id, self.POST_FIELDS)
        return post_from_graph(post)

    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal stats for a post: embedded engagement + post insights.

        Insights failures are tolerated (missing ``read_insights`` permission,
        unpublished posts) so plain engagement counters still come through.
        """
        post = self.client.get_object(post_id, self.POST_FIELDS)

        insights = None
        try:
            insights = insights_to_dict(self.client.get_insights(post_id, POST_INSIGHT_METRICS))
        except ConnectorError:
            insights = None

        stats = post_stats_from_graph(post, insights)
        if stats.post_id != post_id:
            stats = stats.model_copy(update={"post_id": post_id})
        return stats

    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch Page-level stats: followers + daily impressions/reach summed over the period.

        Insights failures are tolerated so lifetime counters (followers) still
        come through when the token lacks ``read_insights``.
        """
        page = self.client.get_object(self.page_id, self.PAGE_FIELDS)

        insights = None
        try:
            payload = self.client.get_insights(
                self.page_id,
                PAGE_INSIGHT_METRICS,
                period="day",
                since=int(since.timestamp()) if since else None,
                until=int(until.timestamp()) if until else None,
            )
            insights = insights_to_totals(payload)
        except ConnectorError:
            insights = None

        stats = account_stats_from_page(page, insights)
        return stats.model_copy(update={"period_start": since, "period_end": until})

    # ── SocialPublishCapability ──

    def publish_post(self, draft: SocialPostDraft) -> PublishResult:
        """Publish a feed post, photo or video to the Page.

        Facebook Pages have no per-post privacy — Page posts are always public,
        so drafts with a non-PUBLIC privacy are rejected. Scheduling and
        unpublished posts go through ``draft.extra`` (``published``,
        ``scheduled_publish_time``), which is merged into the payload last.
        """
        if draft.privacy != SocialPrivacy.PUBLIC:
            raise ValidationError(
                "Facebook Pages publish publicly only; use draft.extra['published']=False for unpublished posts"
            )

        has_media = bool(draft.media_url or draft.file_path or draft.content is not None)
        if not has_media:
            return self._publish_feed_post(draft)
        if draft.media_type == SocialMediaType.IMAGE:
            return self._publish_photo(draft)
        if draft.media_type in (SocialMediaType.VIDEO, SocialMediaType.SHORT_VIDEO):
            return self._publish_video(draft)
        raise ValidationError(f"Facebook Pages cannot publish media of type '{draft.media_type}'")

    def check_publish_status(self, publish_id: str) -> PublishResult:
        """Poll an asynchronous video publish; feed posts/photos report PUBLISHED directly."""
        obj = self.client.get_object(publish_id, "status,permalink_url")

        status = obj.get("status") or {}
        if not status:
            # Feed posts and photos have no status field — they publish synchronously.
            return PublishResult(
                post_id=publish_id,
                publish_id=publish_id,
                status=PublishStatus.PUBLISHED,
                url=self._absolute_permalink(obj.get("permalink_url", "") or ""),
            )

        video_status = status.get("video_status", "")
        if video_status == "ready":
            return PublishResult(
                post_id=publish_id,
                publish_id=publish_id,
                status=PublishStatus.PUBLISHED,
                url=self._absolute_permalink(obj.get("permalink_url", "") or ""),
            )
        if video_status == "error":
            return PublishResult(
                publish_id=publish_id,
                status=PublishStatus.FAILED,
                error=f"Facebook video processing failed (video {publish_id})",
            )
        return PublishResult(publish_id=publish_id, status=PublishStatus.PROCESSING)

    def _publish_feed_post(self, draft: SocialPostDraft) -> PublishResult:
        """POST {page_id}/feed — text/link post."""
        message = draft.description or draft.title
        payload = {}
        if message:
            payload["message"] = message
        if draft.link:
            payload["link"] = draft.link
        if not payload:
            raise ValidationError("Facebook feed posts require a message (description/title) or a link")
        payload.update(draft.extra)
        response = self.client.post_edge(self.page_id, "feed", payload)
        return publish_result_from_graph(response, self.page_id, is_video=False)

    def _publish_photo(self, draft: SocialPostDraft) -> PublishResult:
        """POST {page_id}/photos — remote URL or multipart upload."""
        if draft.media_url:
            payload = {"url": draft.media_url, "caption": draft.description, **draft.extra}
            response = self.client.post_edge(self.page_id, "photos", payload)
        else:
            filename, content = self._media_file(draft)
            data = {"caption": draft.description, **draft.extra}
            response = self.client.post_edge_multipart(
                self.page_id, "photos", files={"source": (filename, content)}, data=data
            )
        return publish_result_from_graph(response, self.page_id, is_video=False)

    def _publish_video(self, draft: SocialPostDraft) -> PublishResult:
        """POST {page_id}/videos — remote URL or multipart upload; Meta transcodes asynchronously."""
        if draft.media_url:
            payload = {
                "file_url": draft.media_url,
                "description": draft.description,
                "title": draft.title,
                **draft.extra,
            }
            response = self.client.post_edge(self.page_id, "videos", payload)
        else:
            filename, content = self._media_file(draft)
            data = {"description": draft.description, "title": draft.title, **draft.extra}
            response = self.client.post_edge_multipart(
                self.page_id, "videos", files={"source": (filename, content)}, data=data
            )
        return publish_result_from_graph(response, self.page_id, is_video=True)

    def _media_file(self, draft: SocialPostDraft) -> tuple[str, bytes]:
        """Resolve the local media source (content bytes or file_path) to (filename, bytes)."""
        if draft.content is not None:
            return draft.filename or "upload", draft.content
        path = Path(draft.file_path)
        return draft.filename or path.name, path.read_bytes()

    @staticmethod
    def _absolute_permalink(permalink_url: str) -> str:
        """Graph often returns relative permalinks (``/{page}/videos/{id}``) — make them absolute."""
        if not permalink_url or permalink_url.startswith("http"):
            return permalink_url
        return f"https://www.facebook.com{permalink_url}"
