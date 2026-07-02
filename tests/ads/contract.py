"""
Ads port contract test suite.

Reusable tests that any AdsPort adapter must pass. Provider test modules
subclass AdsContractTests and provide fixtures:

- ``adapter``: adapter backed by a FakeHttpClient with canned responses
- ``campaign_draft`` / ``ad_group_draft`` / ``ad_draft``: DTOs with empty id
  that the fake backend accepts for creation
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.dto import PaginatedResult
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
)
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import ProviderFamily


class AdsContractTests:
    """Contract tests for AdsPort implementations."""

    @pytest.fixture
    def adapter(self) -> AdsPort:
        raise NotImplementedError

    def test_is_ads_port_instance(self, adapter: AdsPort):
        assert isinstance(adapter, AdsPort)

    def test_manifest_valid(self, adapter: AdsPort):
        assert adapter.manifest.validate() == []
        assert adapter.manifest.family == ProviderFamily.ADS

    def test_registered(self, adapter: AdsPort):
        assert registry.is_registered("ads", adapter.manifest.name)

    def test_declared_capabilities_implemented(self, adapter: AdsPort):
        for capability in adapter.manifest.capabilities:
            assert adapter.supports(capability)

    def test_validate_credentials(self, adapter: AdsPort):
        assert adapter.validate_credentials() is True

    # ── Campaigns ──

    def test_list_campaigns(self, adapter: AdsPort):
        result = adapter.list_campaigns()
        assert isinstance(result, PaginatedResult)
        assert result.items
        for campaign in result.items:
            assert isinstance(campaign, AdCampaign)
            assert campaign.id

    def test_get_campaign(self, adapter: AdsPort, sample_campaign_id: str):
        campaign = adapter.get_campaign(sample_campaign_id)
        assert isinstance(campaign, AdCampaign)
        assert campaign.id == sample_campaign_id

    def test_create_campaign(self, adapter: AdsPort, campaign_draft: AdCampaign):
        created = adapter.create_campaign(campaign_draft)
        assert isinstance(created, AdCampaign)
        assert created.id

    def test_set_campaign_status(self, adapter: AdsPort, sample_campaign_id: str):
        campaign = adapter.set_campaign_status(sample_campaign_id, AdEntityStatus.PAUSED)
        assert isinstance(campaign, AdCampaign)

    # ── Ad groups ──

    def test_list_ad_groups(self, adapter: AdsPort, sample_campaign_id: str):
        result = adapter.list_ad_groups(campaign_id=sample_campaign_id)
        assert isinstance(result, PaginatedResult)
        assert result.items
        for ad_group in result.items:
            assert isinstance(ad_group, AdGroup)
            assert ad_group.id

    def test_create_ad_group(self, adapter: AdsPort, ad_group_draft: AdGroup):
        created = adapter.create_ad_group(ad_group_draft)
        assert isinstance(created, AdGroup)
        assert created.id

    def test_set_ad_group_status(self, adapter: AdsPort, sample_ad_group_id: str):
        ad_group = adapter.set_ad_group_status(sample_ad_group_id, AdEntityStatus.PAUSED)
        assert isinstance(ad_group, AdGroup)

    # ── Ads ──

    def test_list_ads(self, adapter: AdsPort, sample_ad_group_id: str):
        result = adapter.list_ads(ad_group_id=sample_ad_group_id)
        assert isinstance(result, PaginatedResult)
        assert result.items
        for ad in result.items:
            assert isinstance(ad, Ad)
            assert ad.id

    def test_create_ad(self, adapter: AdsPort, ad_draft: Ad):
        created = adapter.create_ad(ad_draft)
        assert isinstance(created, Ad)
        assert created.id

    def test_set_ad_status(self, adapter: AdsPort, sample_ad_id: str):
        ad = adapter.set_ad_status(sample_ad_id, AdEntityStatus.PAUSED)
        assert isinstance(ad, Ad)

    # ── Universal insights ──

    def test_get_campaign_insights(self, adapter: AdsPort, sample_campaign_id: str):
        insights = adapter.get_insights(AdInsightsLevel.CAMPAIGN, entity_id=sample_campaign_id)
        assert isinstance(insights, list)
        assert insights
        for row in insights:
            assert isinstance(row, AdInsights)
            assert row.level == AdInsightsLevel.CAMPAIGN
            # Universal stats interface: core spend/delivery metrics must be mapped
            assert any(value is not None for value in (row.impressions, row.clicks, row.spend))
