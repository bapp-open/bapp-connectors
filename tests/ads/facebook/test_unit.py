"""
Facebook/Meta Ads adapter unit tests + contract tests.

All tests run against a FakeHttpClient with canned Graph API responses.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsightsLevel,
    AdObjective,
    AdTargeting,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.ads.facebook.adapter import MetaAdsAdapter
from bapp_connectors.providers.ads.facebook.mappers import (
    META_TO_OBJECTIVE,
    OBJECTIVE_TO_META,
    STATUS_TO_META,
    ad_from_meta,
    campaign_to_meta_payload,
    insights_from_meta,
    objective_from_meta,
    status_from_meta,
    targeting_from_meta,
    targeting_to_meta,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

ACCOUNT_ID = "123"

CAMPAIGN_ROW = {
    "id": "camp_1",
    "name": "Spring Sale",
    "status": "ACTIVE",
    "effective_status": "ACTIVE",
    "objective": "OUTCOME_TRAFFIC",
    "daily_budget": "1000",
    "start_time": "2026-06-01T00:00:00+0000",
}

ADSET_ROW = {
    "id": "set_1",
    "name": "RO adults",
    "campaign_id": "camp_1",
    "status": "ACTIVE",
    "effective_status": "ACTIVE",
    "daily_budget": "500",
    "bid_amount": "150",
    "targeting": {"geo_locations": {"countries": ["RO"]}, "age_min": 18, "genders": [2]},
}

AD_ROW = {
    "id": "ad_1",
    "name": "Ad one",
    "adset_id": "set_1",
    "campaign_id": "camp_1",
    "status": "ACTIVE",
    "effective_status": "ACTIVE",
    "creative": {
        "id": "cr_1",
        "title": "Big sale",
        "body": "Buy now",
        "image_url": "https://cdn.example/img.jpg",
        "thumbnail_url": "https://cdn.example/thumb.jpg",
    },
}

INSIGHTS_ROW = {
    "campaign_id": "camp_1",
    "impressions": "1000",
    "clicks": "50",
    "spend": "12.34",
    "ctr": "5.0",
    "cpc": "0.25",
    "cpm": "12.34",
    "reach": "800",
    "frequency": "1.25",
    "account_currency": "RON",
    "actions": [
        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
        {"action_type": "link_click", "value": "50"},
    ],
    "action_values": [{"action_type": "offsite_conversion.fb_pixel_purchase", "value": "150.5"}],
    "video_play_actions": [{"action_type": "video_view", "value": "40"}],
    "date_start": "2026-06-01",
    "date_stop": "2026-06-30",
}


def _edge(rows: list[dict]) -> dict:
    return {"data": rows, "paging": {"cursors": {"before": "b", "after": "a"}}}


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient()
    # Order matters: substring rules — insights and account-edge rules go first.
    fake.add("GET", "/insights", _edge([INSIGHTS_ROW]))
    fake.add("GET", f"act_{ACCOUNT_ID}/adsets", _edge([ADSET_ROW]))
    fake.add("POST", f"act_{ACCOUNT_ID}/adsets", {"id": "set_new"})
    fake.add("GET", f"act_{ACCOUNT_ID}/ads", _edge([AD_ROW]))
    fake.add("POST", f"act_{ACCOUNT_ID}/ads", {"id": "ad_new"})
    fake.add("GET", f"act_{ACCOUNT_ID}/campaigns", _edge([CAMPAIGN_ROW]))
    fake.add("POST", f"act_{ACCOUNT_ID}/campaigns", {"id": "camp_new"})
    fake.add("GET", "camp_new", {**CAMPAIGN_ROW, "id": "camp_new"})
    fake.add("GET", "camp_1", CAMPAIGN_ROW)
    fake.add("POST", "camp_1", {"success": True})
    fake.add("GET", "set_new", {**ADSET_ROW, "id": "set_new"})
    fake.add("GET", "set_1", ADSET_ROW)
    fake.add("POST", "set_1", {"success": True})
    fake.add("GET", "ad_new", {**AD_ROW, "id": "ad_new"})
    fake.add("GET", "ad_1", AD_ROW)
    fake.add("POST", "ad_1", {"success": True})
    fake.add("GET", f"act_{ACCOUNT_ID}", {"id": f"act_{ACCOUNT_ID}", "name": "Test Account", "currency": "RON"})
    return fake


@pytest.fixture
def adapter(fake_http: FakeHttpClient) -> MetaAdsAdapter:
    return MetaAdsAdapter(
        credentials={"token": "test-token", "ad_account_id": ACCOUNT_ID},
        http_client=fake_http,
    )


class TestMetaAdsContract(AdsContractTests):
    """Run all AdsPort contract tests against the Meta adapter."""

    @pytest.fixture
    def adapter(self, fake_http: FakeHttpClient) -> MetaAdsAdapter:
        return MetaAdsAdapter(
            credentials={"token": "test-token", "ad_account_id": ACCOUNT_ID},
            http_client=fake_http,
        )

    @pytest.fixture
    def sample_campaign_id(self) -> str:
        return "camp_1"

    @pytest.fixture
    def sample_ad_group_id(self) -> str:
        return "set_1"

    @pytest.fixture
    def sample_ad_id(self) -> str:
        return "ad_1"

    @pytest.fixture
    def campaign_draft(self) -> AdCampaign:
        return AdCampaign(name="Contract Campaign", objective=AdObjective.TRAFFIC, daily_budget=Decimal("10"))

    @pytest.fixture
    def ad_group_draft(self) -> AdGroup:
        return AdGroup(
            campaign_id="camp_1",
            name="Contract Ad Set",
            daily_budget=Decimal("5"),
            targeting=AdTargeting(countries=["RO"], age_min=18),
        )

    @pytest.fixture
    def ad_draft(self) -> Ad:
        return Ad(ad_group_id="set_1", name="Contract Ad", creative=AdCreative(id="123"))


class TestBudgetConversion:
    """Budgets cross the boundary as Decimals; Meta wants cents-as-strings."""

    def test_campaign_create_converts_budget_to_cents(self, adapter, fake_http):
        adapter.create_campaign(AdCampaign(name="Budget", objective=AdObjective.TRAFFIC, daily_budget=Decimal("10")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and f"act_{ACCOUNT_ID}/campaigns" in c.path)
        assert create_call.kwargs["json"]["daily_budget"] == "1000"
        assert create_call.kwargs["json"]["objective"] == "OUTCOME_TRAFFIC"
        assert create_call.kwargs["json"]["status"] == "PAUSED"
        assert create_call.kwargs["json"]["special_ad_categories"] == []

    def test_ad_group_create_converts_budget_and_bid(self, adapter, fake_http):
        adapter.create_ad_group(
            AdGroup(campaign_id="camp_1", name="Bid", daily_budget=Decimal("5.50"), bid_amount=Decimal("1.25"))
        )
        create_call = next(c for c in fake_http.calls if c.method == "POST" and f"act_{ACCOUNT_ID}/adsets" in c.path)
        assert create_call.kwargs["json"]["daily_budget"] == "550"
        assert create_call.kwargs["json"]["bid_amount"] == "125"
        assert create_call.kwargs["json"]["billing_event"] == "IMPRESSIONS"
        assert create_call.kwargs["json"]["optimization_goal"] == "LINK_CLICKS"

    def test_budget_read_converts_cents_to_decimal(self, adapter):
        campaign = adapter.get_campaign("camp_1")
        assert campaign.daily_budget == Decimal("10")
        ad_group = adapter.get_ad_group("set_1")
        assert ad_group.daily_budget == Decimal("5")
        assert ad_group.bid_amount == Decimal("1.5")

    def test_update_campaign_partial_changes(self, adapter, fake_http):
        adapter.update_campaign("camp_1", {"daily_budget": Decimal("20"), "name": "Renamed"})
        update_call = next(c for c in fake_http.calls if c.method == "POST" and c.path == "camp_1")
        assert update_call.kwargs["json"] == {"name": "Renamed", "daily_budget": "2000"}


class TestTargetingMapping:
    def test_targeting_to_meta(self):
        spec = targeting_to_meta(
            AdTargeting(countries=["RO", "HU"], age_min=18, age_max=45, genders=["male", "female"])
        )
        assert spec["geo_locations"] == {"countries": ["RO", "HU"]}
        assert spec["age_min"] == 18
        assert spec["age_max"] == 45
        assert spec["genders"] == [1, 2]

    def test_targeting_to_meta_merges_extra(self):
        spec = targeting_to_meta(AdTargeting(countries=["RO"], extra={"publisher_platforms": ["facebook"]}))
        assert spec["publisher_platforms"] == ["facebook"]

    def test_targeting_from_meta(self):
        targeting = targeting_from_meta(
            {"geo_locations": {"countries": ["RO"]}, "age_min": 21, "genders": [2], "device_platforms": ["mobile"]}
        )
        assert targeting.countries == ["RO"]
        assert targeting.age_min == 21
        assert targeting.genders == ["female"]
        assert targeting.extra == {"device_platforms": ["mobile"]}


class TestObjectiveAndStatusMaps:
    def test_objective_round_trip(self):
        for objective in (
            AdObjective.AWARENESS,
            AdObjective.TRAFFIC,
            AdObjective.ENGAGEMENT,
            AdObjective.LEADS,
            AdObjective.APP_PROMOTION,
            AdObjective.SALES,
        ):
            assert META_TO_OBJECTIVE[OBJECTIVE_TO_META[objective]] == objective

    def test_legacy_objectives(self):
        assert objective_from_meta("LINK_CLICKS") == AdObjective.TRAFFIC
        assert objective_from_meta("CONVERSIONS") == AdObjective.SALES
        assert objective_from_meta("VIDEO_VIEWS") == AdObjective.VIDEO_VIEWS
        assert objective_from_meta("SOMETHING_NEW") == AdObjective.OTHER

    def test_status_round_trip(self):
        for status, meta in STATUS_TO_META.items():
            assert status_from_meta({"status": meta}) == status

    def test_effective_status_pending_review(self):
        ad = ad_from_meta({**AD_ROW, "effective_status": "PENDING_REVIEW"})
        assert ad.status == AdEntityStatus.PENDING_REVIEW

    def test_effective_status_rejected_and_parent_paused(self):
        assert status_from_meta({"effective_status": "DISAPPROVED"}) == AdEntityStatus.REJECTED
        assert status_from_meta({"effective_status": "WITH_ISSUES"}) == AdEntityStatus.REJECTED
        assert status_from_meta({"effective_status": "CAMPAIGN_PAUSED"}) == AdEntityStatus.PAUSED
        assert status_from_meta({"effective_status": "ADSET_PAUSED"}) == AdEntityStatus.PAUSED
        assert status_from_meta({"effective_status": "SOMETHING_ELSE"}) == AdEntityStatus.UNKNOWN

    def test_set_status_sends_mapped_value(self, adapter, fake_http):
        adapter.set_campaign_status("camp_1", AdEntityStatus.ARCHIVED)
        update_call = next(c for c in fake_http.calls if c.method == "POST" and c.path == "camp_1")
        assert update_call.kwargs["json"] == {"status": "ARCHIVED"}

    def test_status_default_paused_only_on_create(self):
        assert campaign_to_meta_payload({"name": "x"}, for_create=True)["status"] == "PAUSED"
        assert "status" not in campaign_to_meta_payload({"name": "x"})


class TestInsightsMapping:
    def test_insights_row_mapping(self):
        insights = insights_from_meta(INSIGHTS_ROW, AdInsightsLevel.CAMPAIGN)
        assert insights.entity_id == "camp_1"
        assert insights.impressions == 1000
        assert insights.clicks == 50
        assert insights.spend == Decimal("12.34")  # spend is currency units, not cents
        assert insights.currency == "RON"
        assert insights.ctr == 5.0
        assert insights.cpc == Decimal("0.25")
        assert insights.cpm == Decimal("12.34")
        assert insights.reach == 800
        assert insights.frequency == 1.25
        assert insights.conversions == 3.0
        assert insights.conversion_value == Decimal("150.5")
        assert insights.video_views == 40
        assert insights.date_start is not None and insights.date_start.year == 2026
        assert insights.date_stop is not None and insights.date_stop.month == 6

    def test_insights_missing_metrics_are_none(self):
        insights = insights_from_meta({"impressions": "10"}, AdInsightsLevel.AD)
        assert insights.impressions == 10
        assert insights.spend is None
        assert insights.conversions is None
        assert insights.conversion_value is None
        assert insights.video_views is None

    def test_insights_conversions_none_when_no_matching_actions(self):
        insights = insights_from_meta({"actions": [{"action_type": "link_click", "value": "5"}]}, AdInsightsLevel.AD)
        assert insights.conversions is None

    def test_video_views_fall_back_to_actions(self):
        row = {"actions": [{"action_type": "video_view", "value": "7"}]}
        assert insights_from_meta(row, AdInsightsLevel.AD).video_views == 7

    def test_get_insights_params(self, adapter, fake_http):
        from datetime import datetime

        adapter.get_insights(
            AdInsightsLevel.AD_GROUP, entity_id="set_1", since=datetime(2026, 6, 1), until=datetime(2026, 6, 30)
        )
        call = fake_http.last_call()
        assert call.path == "set_1/insights"
        assert call.kwargs["params"]["level"] == "adset"
        assert call.kwargs["params"]["time_range"] == '{"since": "2026-06-01", "until": "2026-06-30"}'

    def test_get_insights_account_level_defaults_to_account_object(self, adapter, fake_http):
        adapter.get_insights(AdInsightsLevel.ACCOUNT)
        assert fake_http.last_call().path == f"act_{ACCOUNT_ID}/insights"


class TestAdCreative:
    def test_create_ad_without_creative_raises(self, adapter):
        with pytest.raises(ValidationError):
            adapter.create_ad(Ad(ad_group_id="set_1", name="No creative"))

    def test_create_ad_with_creative_id(self, adapter, fake_http):
        adapter.create_ad(Ad(ad_group_id="set_1", name="With creative", creative=AdCreative(id="cr_9")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and f"act_{ACCOUNT_ID}/ads" in c.path)
        assert create_call.kwargs["json"]["creative"] == {"creative_id": "cr_9"}
        assert create_call.kwargs["json"]["adset_id"] == "set_1"

    def test_create_ad_with_object_story_spec(self, adapter, fake_http):
        spec = {"page_id": "42", "link_data": {"link": "https://example.com"}}
        adapter.create_ad(Ad(ad_group_id="set_1", name="Story", extra={"object_story_spec": spec}))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and f"act_{ACCOUNT_ID}/ads" in c.path)
        assert create_call.kwargs["json"]["creative"] == {"object_story_spec": spec}

    def test_ad_from_meta_maps_creative(self):
        ad = ad_from_meta(AD_ROW)
        assert ad.creative is not None
        assert ad.creative.id == "cr_1"
        assert ad.creative.title == "Big sale"
        assert ad.creative.body == "Buy now"
        assert ad.creative.media_url == "https://cdn.example/img.jpg"
        assert ad.creative.thumbnail_url == "https://cdn.example/thumb.jpg"


class TestConnectionAndFiltering:
    def test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "Test Account" in result.message

    def test_list_ad_groups_filters_by_campaign(self, adapter, fake_http):
        adapter.list_ad_groups(campaign_id="camp_1")
        call = fake_http.last_call()
        assert '"field": "campaign.id"' in call.kwargs["params"]["filtering"]
        assert '"value": "camp_1"' in call.kwargs["params"]["filtering"]

    def test_list_ads_filters_by_adset(self, adapter, fake_http):
        adapter.list_ads(ad_group_id="set_1")
        call = fake_http.last_call()
        assert '"field": "adset.id"' in call.kwargs["params"]["filtering"]

    def test_pagination_cursor(self, adapter, fake_http):
        fake_http.responses.insert(
            0,
            (
                "GET",
                f"act_{ACCOUNT_ID}/campaigns",
                {
                    "data": [CAMPAIGN_ROW],
                    "paging": {"cursors": {"after": "cursor_xyz"}, "next": "https://graph.facebook.com/next"},
                },
            ),
        )
        result = adapter.list_campaigns()
        assert result.cursor == "cursor_xyz"
        assert result.has_more is True
