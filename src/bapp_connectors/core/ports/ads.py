"""
Ads port — contract for advertising platform connectors.

Ads providers (Facebook/Meta Ads, TikTok Ads, Google Ads, ...) manage the
normalized campaign → ad group → ad hierarchy and report performance through
the universal AdInsights DTO.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .base import BasePort

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto.ads import (
        Ad,
        AdCampaign,
        AdEntityStatus,
        AdGroup,
        AdInsights,
        AdInsightsLevel,
    )
    from bapp_connectors.core.dto.base import PaginatedResult


class AdsPort(BasePort):
    """
    Common contract for all advertising connectors.

    Naming is normalized: an *ad group* is Meta's "ad set", TikTok's "adgroup",
    and Google's "ad group". Status changes (pause/resume/delete) go through
    the ``set_*_status`` methods — platforms that cannot hard-delete map
    ``AdEntityStatus.DELETED`` to their closest equivalent (e.g. REMOVED).
    """

    # ── Campaigns ──

    @abstractmethod
    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        """List campaigns in the connected ad account."""
        ...

    @abstractmethod
    def get_campaign(self, campaign_id: str) -> AdCampaign:
        """Fetch a single campaign."""
        ...

    @abstractmethod
    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        """Create a campaign from a DTO with empty ``id``. Returns it with the platform ID."""
        ...

    @abstractmethod
    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        """Update campaign fields (normalized DTO field names) and return the updated campaign."""
        ...

    @abstractmethod
    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        """Pause, resume, or delete a campaign."""
        ...

    # ── Ad groups ──

    @abstractmethod
    def list_ad_groups(
        self, campaign_id: str | None = None, cursor: str | None = None
    ) -> PaginatedResult[AdGroup]:
        """List ad groups, optionally filtered to one campaign."""
        ...

    @abstractmethod
    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        """Fetch a single ad group."""
        ...

    @abstractmethod
    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        """Create an ad group from a DTO with empty ``id``. Returns it with the platform ID."""
        ...

    @abstractmethod
    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        """Update ad group fields (normalized DTO field names) and return the updated ad group."""
        ...

    @abstractmethod
    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        """Pause, resume, or delete an ad group."""
        ...

    # ── Ads ──

    @abstractmethod
    def list_ads(
        self, ad_group_id: str | None = None, cursor: str | None = None
    ) -> PaginatedResult[Ad]:
        """List ads, optionally filtered to one ad group."""
        ...

    @abstractmethod
    def get_ad(self, ad_id: str) -> Ad:
        """Fetch a single ad."""
        ...

    @abstractmethod
    def create_ad(self, ad: Ad) -> Ad:
        """Create an ad from a DTO with empty ``id``. Returns it with the platform ID."""
        ...

    @abstractmethod
    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        """Update ad fields (normalized DTO field names) and return the updated ad."""
        ...

    @abstractmethod
    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        """Pause, resume, or delete an ad."""
        ...

    # ── Universal insights ──

    @abstractmethod
    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        """Fetch universal performance metrics.

        Args:
            level: Aggregation level (account, campaign, ad_group, ad).
            entity_id: Restrict to one entity at that level; ``None`` returns
                insights for all entities at the level (account level ignores it).
            since/until: Reporting period; provider default applies when omitted.
        """
        ...
