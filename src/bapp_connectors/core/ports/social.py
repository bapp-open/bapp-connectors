"""
Social port — contract for social media platform connectors.

Social providers (TikTok, YouTube Shorts, Facebook, ...) expose accounts,
posts, and a *universal stats interface*: the same SocialPostStats /
SocialAccountStats DTOs regardless of platform, so callers can aggregate
metrics across platforms without provider-specific code.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .base import BasePort

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.base import PaginatedResult
    from bapp_connectors.core.dto.social import (
        SocialAccount,
        SocialAccountStats,
        SocialPost,
        SocialPostStats,
    )


class SocialPort(BasePort):
    """
    Common contract for all social media connectors.

    Metrics a platform does not expose are returned as ``None`` in the stats
    DTOs; platform-specific metrics are preserved in ``extra``.
    """

    @abstractmethod
    def get_account(self) -> SocialAccount:
        """Fetch the connected account/channel/page profile."""
        ...

    @abstractmethod
    def list_posts(self, limit: int = 25, cursor: str | None = None) -> PaginatedResult[SocialPost]:
        """List posts/videos of the connected account, newest first.

        Posts include ``stats`` when the platform returns metrics with the
        listing; otherwise call :meth:`get_post_stats` per post.
        """
        ...

    @abstractmethod
    def get_post(self, post_id: str) -> SocialPost:
        """Fetch a single post/video by its platform ID."""
        ...

    @abstractmethod
    def get_post_stats(self, post_id: str) -> SocialPostStats:
        """Fetch universal statistics for a single post/video."""
        ...

    @abstractmethod
    def get_account_stats(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> SocialAccountStats:
        """Fetch universal account-level statistics.

        ``since``/``until`` scope period-based metrics (impressions, reach)
        where the platform supports it; lifetime counters (followers, total
        views) are returned as-is regardless of the period.
        """
        ...
