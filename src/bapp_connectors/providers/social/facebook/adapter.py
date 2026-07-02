"""
Facebook Page social adapter — implements SocialPort.

Covers a Facebook *Page* via the Graph API v19.0: page profile, published
posts (including Reels as they appear in the posts edge), per-post stats,
and page-level insights.

Auth: Page access token sent as a Bearer header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.errors import ConnectorError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.facebook.client import FacebookGraphClient
from bapp_connectors.providers.social.facebook.manifest import manifest
from bapp_connectors.providers.social.facebook.mappers import (
    account_from_page,
    account_stats_from_page,
    insights_to_dict,
    insights_to_totals,
    post_from_graph,
    post_stats_from_graph,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostStats,
    )

POST_INSIGHT_METRICS = "post_impressions,post_impressions_unique,post_clicks,post_video_views"
PAGE_INSIGHT_METRICS = "page_impressions,page_impressions_unique"


class FacebookSocialAdapter(SocialPort):
    """
    Facebook Page adapter (Graph API v19.0).

    Implements SocialPort for a single Facebook Page: account profile, posts
    listing (incl. Reels posts surfaced on the posts edge), per-post stats via
    post insights, and account stats via page insights. Insights calls degrade
    gracefully — when the token lacks ``read_insights`` the engagement counters
    embedded in post objects are still returned.
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

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(credentials.get("token", "")),
                provider_name="facebook",
            )

        self.client = FacebookGraphClient(http_client=http_client)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

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
