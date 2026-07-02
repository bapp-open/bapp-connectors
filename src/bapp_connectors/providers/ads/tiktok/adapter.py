"""
TikTok Ads adapter — implements AdsPort via the TikTok Business API v1.3.

Manages the normalized campaign → ad group → ad hierarchy (TikTok "adgroup")
and reports performance through the universal AdInsights DTO.

Auth: access token sent as the ``Access-Token`` header on every call, so the
HTTP client itself uses NoAuth.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bapp_connectors.core.dto import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
    ConnectionTestResult,
    PaginatedResult,
)
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.tiktok.client import TikTokAdsClient
from bapp_connectors.providers.ads.tiktok.manifest import manifest
from bapp_connectors.providers.ads.tiktok.mappers import (
    ad_creative_to_tiktok,
    ad_from_tiktok,
    ad_group_from_tiktok,
    ad_group_to_tiktok_payload,
    ad_to_tiktok_payload,
    campaign_from_tiktok,
    campaign_to_tiktok_payload,
    insights_from_tiktok,
    level_id_dimension,
    status_to_tiktok,
)

DEFAULT_PAGE_SIZE = 20

DATA_LEVELS = {
    AdInsightsLevel.ACCOUNT: "AUCTION_ADVERTISER",
    AdInsightsLevel.CAMPAIGN: "AUCTION_CAMPAIGN",
    AdInsightsLevel.AD_GROUP: "AUCTION_ADGROUP",
    AdInsightsLevel.AD: "AUCTION_AD",
}

REPORT_METRICS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "reach",
    "frequency",
    "conversion",
    "video_play_actions",
]


class TikTokAdsAdapter(AdsPort):
    """
    TikTok Business API v1.3 ads adapter.

    Implements AdsPort: campaign/adgroup/ad CRUD + status changes with
    page-number cursor pagination, and the universal insights interface via
    the synchronous integrated report.
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}
        self.advertiser_id = str(credentials.get("advertiser_id", ""))

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),  # token goes in the Access-Token header per call
                provider_name="tiktok",
            )

        self.client = TikTokAdsClient(
            http_client=http_client,
            access_token=credentials.get("access_token", ""),
            advertiser_id=self.advertiser_id,
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            self.client.get_campaigns(page=1, page_size=1)
            return ConnectionTestResult(
                success=True,
                message=f"Connected to TikTok Ads advertiser {self.advertiser_id}",
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── Pagination ──

    @staticmethod
    def _paginate(data: dict, mapper) -> PaginatedResult:
        """Build a PaginatedResult from a TikTok list envelope.

        The framework cursor is the stringified next page number.
        """
        page_info = data.get("page_info", {}) or {}
        page = int(page_info.get("page", 1))
        total_page = int(page_info.get("total_page", 1))
        has_more = page < total_page
        return PaginatedResult(
            items=[mapper(row) for row in data.get("list", [])],
            cursor=str(page + 1) if has_more else None,
            has_more=has_more,
            total=page_info.get("total_number"),
        )

    @staticmethod
    def _page(cursor: str | None) -> int:
        return int(cursor) if cursor else 1

    # ── Campaigns ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        data = self.client.get_campaigns(page=self._page(cursor), page_size=DEFAULT_PAGE_SIZE)
        return self._paginate(data, campaign_from_tiktok)

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        data = self.client.get_campaigns(page=1, page_size=1, campaign_ids=[campaign_id])
        rows = data.get("list", [])
        if not rows:
            raise PermanentProviderError(f"TikTok campaign not found: {campaign_id}")
        return campaign_from_tiktok(rows[0])

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        payload = campaign_to_tiktok_payload(campaign.model_dump(exclude={"provider_meta"}))
        data = self.client.create_campaign(payload)
        return self.get_campaign(str(data.get("campaign_id", "")))

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        payload = campaign_to_tiktok_payload(changes, partial=True)
        payload["campaign_id"] = campaign_id
        self.client.update_campaign(payload)
        return self.get_campaign(campaign_id)

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        self.client.update_campaign_status([campaign_id], status_to_tiktok(status))
        return self.get_campaign(campaign_id)

    # ── Ad groups ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        data = self.client.get_adgroups(page=self._page(cursor), page_size=DEFAULT_PAGE_SIZE, campaign_id=campaign_id)
        return self._paginate(data, ad_group_from_tiktok)

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        data = self.client.get_adgroups(page=1, page_size=1, adgroup_ids=[ad_group_id])
        rows = data.get("list", [])
        if not rows:
            raise PermanentProviderError(f"TikTok ad group not found: {ad_group_id}")
        return ad_group_from_tiktok(rows[0])

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        payload = ad_group_to_tiktok_payload(ad_group.model_dump(exclude={"provider_meta"}))
        data = self.client.create_adgroup(payload)
        return self.get_ad_group(str(data.get("adgroup_id", "")))

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        payload = ad_group_to_tiktok_payload(changes, partial=True)
        payload["adgroup_id"] = ad_group_id
        self.client.update_adgroup(payload)
        return self.get_ad_group(ad_group_id)

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        self.client.update_adgroup_status([ad_group_id], status_to_tiktok(status))
        return self.get_ad_group(ad_group_id)

    # ── Ads ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        data = self.client.get_ads(page=self._page(cursor), page_size=DEFAULT_PAGE_SIZE, adgroup_id=ad_group_id)
        return self._paginate(data, ad_from_tiktok)

    def get_ad(self, ad_id: str) -> Ad:
        data = self.client.get_ads(page=1, page_size=1, ad_ids=[ad_id])
        rows = data.get("list", [])
        if not rows:
            raise PermanentProviderError(f"TikTok ad not found: {ad_id}")
        return ad_from_tiktok(rows[0])

    def create_ad(self, ad: Ad) -> Ad:
        payload = ad_to_tiktok_payload(ad.model_dump(exclude={"provider_meta"}))
        data = self.client.create_ad(payload)
        ad_ids = data.get("ad_ids") or ([data["ad_id"]] if data.get("ad_id") else [])
        if not ad_ids:
            raise PermanentProviderError("TikTok ad/create/ returned no ad ID.")
        return self.get_ad(str(ad_ids[0]))

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        creative = ad_creative_to_tiktok(changes)
        creative["ad_id"] = ad_id
        payload: dict = {"creatives": [creative]}
        if changes.get("ad_group_id"):
            payload["adgroup_id"] = changes["ad_group_id"]
        self.client.update_ad(payload)
        return self.get_ad(ad_id)

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        self.client.update_ad_status([ad_id], status_to_tiktok(status))
        return self.get_ad(ad_id)

    # ── Universal insights ──

    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        level = AdInsightsLevel(level)
        until = until or datetime.now(UTC)
        since = since or until - timedelta(days=7)
        id_dimension = level_id_dimension(level)

        params: dict = {
            "data_level": DATA_LEVELS[level],
            "dimensions": [id_dimension, "stat_time_day"],
            "metrics": REPORT_METRICS,
            "start_date": since.strftime("%Y-%m-%d"),
            "end_date": until.strftime("%Y-%m-%d"),
        }
        if entity_id and level != AdInsightsLevel.ACCOUNT:
            params["filtering"] = [{"field_name": f"{id_dimension}s", "filter_type": "IN", "filter_value": [entity_id]}]

        data = self.client.get_report(params)
        return [insights_from_tiktok(row, level) for row in data.get("list", [])]
