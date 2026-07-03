"""
Facebook/Meta Ads adapter unit tests + contract tests.

All tests run against a FakeHttpClient with canned Graph API responses.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import CreativeUploadCapability, OAuthCapability
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdEntityStatus,
    AdGroup,
    AdInsightsLevel,
    AdMediaAsset,
    AdMediaType,
    AdObjective,
    AdTargeting,
    UploadedAdMedia,
)
from bapp_connectors.core.errors import AuthenticationError, ConfigurationError, ValidationError
from bapp_connectors.providers.ads.facebook.adapter import MetaAdsAdapter
from bapp_connectors.providers.ads.facebook.manifest import manifest
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


ADIMAGES_RESPONSE = {"images": {"img.jpg": {"hash": "abc123", "url": "https://cdn.fbcdn.example/img.jpg"}}}


@pytest.fixture
def media_http(fake_http: FakeHttpClient) -> FakeHttpClient:
    fake_http.add("POST", f"act_{ACCOUNT_ID}/adimages", ADIMAGES_RESPONSE)
    fake_http.add("POST", f"act_{ACCOUNT_ID}/advideos", {"id": "vid_1"})
    fake_http.add("POST", f"act_{ACCOUNT_ID}/adcreatives", {"id": "cr_new"})
    return fake_http


@pytest.fixture
def page_adapter(media_http: FakeHttpClient) -> MetaAdsAdapter:
    """Adapter configured with the page_id setting required by create_creative."""
    return MetaAdsAdapter(
        credentials={"token": "test-token", "ad_account_id": ACCOUNT_ID},
        http_client=media_http,
        config={"page_id": "42"},
    )


class TestMediaUpload:
    def test_supports_creative_upload_capability(self, adapter):
        assert adapter.supports(CreativeUploadCapability) is True

    def test_upload_image_from_content(self, page_adapter, media_http):
        media = page_adapter.upload_media(
            AdMediaAsset(media_type=AdMediaType.IMAGE, content=b"\xff\xd8jpegbytes", filename="img.jpg")
        )
        call = media_http.last_call()
        assert call.method == "POST"
        assert call.path == f"act_{ACCOUNT_ID}/adimages"
        assert call.kwargs["files"] == {"filename": ("img.jpg", b"\xff\xd8jpegbytes")}
        assert media.id == "abc123"
        assert media.media_type == AdMediaType.IMAGE
        assert media.url == "https://cdn.fbcdn.example/img.jpg"

    def test_upload_image_from_file_path(self, page_adapter, media_http, tmp_path):
        path = tmp_path / "banner.png"
        path.write_bytes(b"pngbytes")
        media = page_adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE, file_path=str(path)))
        assert media_http.last_call().kwargs["files"] == {"filename": ("banner.png", b"pngbytes")}
        assert media.id == "abc123"

    def test_upload_image_with_url_raises(self, page_adapter):
        with pytest.raises(ValidationError):
            page_adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE, url="https://example.com/img.jpg"))

    def test_upload_image_without_source_raises(self, page_adapter):
        with pytest.raises(ValidationError):
            page_adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE))

    def test_upload_video_by_file_url(self, page_adapter, media_http):
        media = page_adapter.upload_media(
            AdMediaAsset(media_type=AdMediaType.VIDEO, url="https://example.com/spot.mp4")
        )
        call = media_http.last_call()
        assert call.path == f"act_{ACCOUNT_ID}/advideos"
        assert call.kwargs["json"] == {"file_url": "https://example.com/spot.mp4"}
        assert media.id == "vid_1"
        assert media.media_type == AdMediaType.VIDEO

    def test_upload_video_from_content(self, page_adapter, media_http):
        page_adapter.upload_media(AdMediaAsset(media_type=AdMediaType.VIDEO, content=b"mp4bytes"))
        assert media_http.last_call().kwargs["files"] == {"source": ("video.mp4", b"mp4bytes")}


class TestCreateCreative:
    def test_create_creative_with_image_media(self, page_adapter, media_http):
        creative = AdCreative(
            title="Big sale",
            body="Buy now",
            call_to_action="SHOP_NOW",
            landing_url="https://example.com/sale",
        )
        media = UploadedAdMedia(id="abc123", media_type=AdMediaType.IMAGE)
        created = page_adapter.create_creative(creative, media)
        call = next(c for c in media_http.calls if c.method == "POST" and "adcreatives" in c.path)
        payload = call.kwargs["json"]
        assert payload["name"] == "Big sale"
        spec = payload["object_story_spec"]
        assert spec["page_id"] == "42"
        assert spec["link_data"]["image_hash"] == "abc123"
        assert spec["link_data"]["link"] == "https://example.com/sale"
        assert spec["link_data"]["message"] == "Buy now"
        assert spec["link_data"]["call_to_action"] == {
            "type": "SHOP_NOW",
            "value": {"link": "https://example.com/sale"},
        }
        assert created.id == "cr_new"

    def test_create_creative_with_video_media(self, page_adapter, media_http):
        creative = AdCreative(
            body="Watch this",
            landing_url="https://example.com",
            thumbnail_url="https://cdn.example/thumb.jpg",
        )
        media = UploadedAdMedia(id="vid_1", media_type=AdMediaType.VIDEO)
        created = page_adapter.create_creative(creative, media)
        call = next(c for c in media_http.calls if c.method == "POST" and "adcreatives" in c.path)
        spec = call.kwargs["json"]["object_story_spec"]
        assert spec["video_data"]["video_id"] == "vid_1"
        assert spec["video_data"]["message"] == "Watch this"
        assert spec["video_data"]["image_url"] == "https://cdn.example/thumb.jpg"
        assert spec["video_data"]["call_to_action"] == {"type": "LEARN_MORE", "value": {"link": "https://example.com"}}
        assert created.id == "cr_new"

    def test_create_creative_without_page_id_raises(self, adapter):
        with pytest.raises(ConfigurationError):
            adapter.create_creative(AdCreative(landing_url="https://example.com"))

    def test_link_data_without_landing_url_raises(self, page_adapter):
        media = UploadedAdMedia(id="abc123", media_type=AdMediaType.IMAGE)
        with pytest.raises(ValidationError):
            page_adapter.create_creative(AdCreative(title="No link"), media)

    def test_create_creative_without_media_or_landing_url_raises(self, page_adapter):
        with pytest.raises(ValidationError):
            page_adapter.create_creative(AdCreative(title="Nothing usable"))

    def test_upload_create_creative_create_ad_flow(self, page_adapter, media_http):
        media = page_adapter.upload_media(
            AdMediaAsset(media_type=AdMediaType.IMAGE, content=b"jpegbytes", filename="img.jpg")
        )
        creative = page_adapter.create_creative(
            AdCreative(title="Flow", body="End to end", landing_url="https://example.com"),
            media,
        )
        ad = page_adapter.create_ad(Ad(ad_group_id="set_1", name="Flow ad", creative=creative))
        create_call = next(c for c in media_http.calls if c.method == "POST" and c.path == f"act_{ACCOUNT_ID}/ads")
        assert create_call.kwargs["json"]["creative"] == {"creative_id": "cr_new"}
        assert ad.id == "ad_new"


OAUTH_SCOPES = ["ads_management", "ads_read", "business_management"]


class TestMetaAdsOAuth:

    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> MetaAdsAdapter:
        return MetaAdsAdapter(
            credentials={"app_id": "app_123", "app_secret": "app_secret_456", "ad_account_id": ACCOUNT_ID},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Facebook"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["app_id", "app_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False
        account_field = next(f for f in manifest.auth.required_fields if f.name == "ad_account_id")
        assert account_field.required is True

    def test_supports_oauth_capability(self, adapter):
        assert adapter.supports(OAuthCapability) is True

    def test_adapter_constructible_with_app_credentials_only(self):
        adapter = MetaAdsAdapter(credentials={"app_id": "app_123", "app_secret": "app_secret_456"})
        assert adapter._app_id == "app_123"
        assert adapter._app_secret == "app_secret_456"
        assert adapter.validate_credentials() is True

    def test_validate_credentials_old_behavior_without_app_credentials(self, adapter):
        assert adapter.validate_credentials() is True  # token + ad_account_id
        no_token = MetaAdsAdapter(credentials={"ad_account_id": ACCOUNT_ID}, http_client=FakeHttpClient())
        assert no_token.validate_credentials() is False

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.facebook.com/v19.0/dialog/oauth?")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["app_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == [",".join(OAUTH_SCOPES)]

    def test_exchange_code_for_token(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "oauth/access_token",
            {"access_token": "USER_TOKEN", "token_type": "bearer", "expires_in": 5183944},
        )
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "oauth/access_token"
        assert call.kwargs["params"]["client_id"] == "app_123"
        assert call.kwargs["params"]["client_secret"] == "app_secret_456"
        assert call.kwargs["params"]["code"] == "the_code"
        assert call.kwargs["params"]["redirect_uri"] == "https://example.com/cb"
        assert tokens.access_token == "USER_TOKEN"
        assert tokens.refresh_token == ""  # Meta has no refresh tokens
        assert tokens.expires_in == 5183944
        assert tokens.extra["credentials"] == {
            "token": "USER_TOKEN",
            "app_id": "app_123",
            "app_secret": "app_secret_456",
        }

    def test_refresh_token_is_long_lived_exchange(self):
        fake = FakeHttpClient()
        fake.add(
            "GET",
            "oauth/access_token",
            {"access_token": "LONG_LIVED_TOKEN", "token_type": "bearer", "expires_in": 5184000},
        )
        tokens = self.make_oauth_adapter(fake).refresh_token("SHORT_LIVED_TOKEN")

        params = fake.last_call().kwargs["params"]
        assert params["grant_type"] == "fb_exchange_token"
        assert params["fb_exchange_token"] == "SHORT_LIVED_TOKEN"
        assert params["client_id"] == "app_123"
        assert params["client_secret"] == "app_secret_456"
        assert tokens.access_token == "LONG_LIVED_TOKEN"
        assert tokens.refresh_token == ""
        assert tokens.expires_in == 5184000


AD_ACCOUNTS_RESPONSE = {
    "data": [
        {"id": "act_123", "account_id": "123", "name": "Main Account", "currency": "RON", "account_status": 1},
        {"id": "act_456", "account_id": 456, "name": "Backup", "currency": "EUR", "account_status": 2},
    ],
    "paging": {"cursors": {"before": "b", "after": "a"}},
}


class TestListAdAccounts:
    """Connect-flow helper: me/adaccounts with the user token from the code exchange."""

    def make_oauth_adapter(self, fake: FakeHttpClient) -> MetaAdsAdapter:
        return MetaAdsAdapter(
            credentials={"app_id": "app_123", "app_secret": "app_secret_456"},
            http_client=fake,
        )

    def test_returns_picker_rows(self):
        fake = FakeHttpClient()
        fake.add("GET", "me/adaccounts", AD_ACCOUNTS_RESPONSE)
        accounts = self.make_oauth_adapter(fake).list_ad_accounts("USER_TOKEN")
        assert accounts == [
            {"ad_account_id": "123", "name": "Main Account", "currency": "RON", "status": 1},
            {"ad_account_id": "456", "name": "Backup", "currency": "EUR", "status": 2},
        ]

    def test_user_token_sent_as_param(self):
        fake = FakeHttpClient()
        fake.add("GET", "me/adaccounts", AD_ACCOUNTS_RESPONSE)
        self.make_oauth_adapter(fake).list_ad_accounts("USER_TOKEN")
        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "me/adaccounts"
        assert call.kwargs["params"]["access_token"] == "USER_TOKEN"
        assert call.kwargs["params"]["fields"] == "id,account_id,name,currency,account_status"

    def test_error_payload_routed_through_check_payload(self):
        fake = FakeHttpClient()
        fake.add("GET", "me/adaccounts", {"error": {"message": "bad token", "type": "OAuthException", "code": 190}})
        with pytest.raises(AuthenticationError):
            self.make_oauth_adapter(fake).list_ad_accounts("EXPIRED_TOKEN")
