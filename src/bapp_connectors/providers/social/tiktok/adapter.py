"""
TikTok Display API social adapter — implements SocialPort.

Exposes the connected TikTok account profile, its videos with cursor
pagination, and universal statistics via the TikTok Display API v2.

Auth: TikTok Login Kit OAuth user access token sent as a Bearer header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import SocialPort
from bapp_connectors.providers.social.tiktok.client import TikTokApiClient
from bapp_connectors.providers.social.tiktok.manifest import manifest
from bapp_connectors.providers.social.tiktok.mappers import (
    account_from_tiktok,
    account_stats_from_tiktok,
    post_from_tiktok,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostStats,
    )


class TikTokSocialAdapter(SocialPort):
    """
    TikTok Display API v2 adapter.

    Implements SocialPort: account profile, video listing with cursor
    pagination, single-video lookup, and the universal stats interface.

    TikTok exposes lifetime counters only — account stats ignore the
    since/until period for filtering but pass it through in the result.
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

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
        return len(missing) == 0

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
