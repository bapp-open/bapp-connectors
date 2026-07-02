"""
TikTok Ads provider unit tests — contract suite + provider-specific behavior.

All HTTP is faked with canned TikTok Business API envelopes:
    {"code": 0, "message": "OK", "request_id": "...", "data": {...}}
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import CreativeUploadCapability, OAuthCapability
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdCreative,
    AdGroup,
    AdInsightsLevel,
    AdMediaAsset,
    AdMediaType,
    AdObjective,
    AdTargeting,
    UploadedAdMedia,
)
from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    UnsupportedFeatureError,
    ValidationError,
)
from bapp_connectors.providers.ads.tiktok import TikTokAdsAdapter
from bapp_connectors.providers.ads.tiktok.errors import check_response
from bapp_connectors.providers.ads.tiktok.manifest import manifest
from bapp_connectors.providers.ads.tiktok.mappers import (
    age_groups_to_range,
    age_range_to_groups,
    campaign_to_tiktok_payload,
    insights_from_tiktok,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

# ── Canned TikTok payloads ──

CAMPAIGN_RAW = {
    "campaign_id": "cmp1",
    "campaign_name": "Summer Sale",
    "operation_status": "ENABLE",
    "objective_type": "TRAFFIC",
    "budget_mode": "BUDGET_MODE_DAY",
    "budget": 50.0,
    "create_time": "2026-06-01 10:00:00",
    "modify_time": "2026-06-02 10:00:00",
}

ADGROUP_RAW = {
    "adgroup_id": "ag1",
    "adgroup_name": "Women 18-34",
    "campaign_id": "cmp1",
    "operation_status": "ENABLE",
    "budget_mode": "BUDGET_MODE_DAY",
    "budget": 20.0,
    "bid_price": 0.5,
    "schedule_start_time": "2026-06-01 00:00:00",
    "schedule_end_time": "2026-06-30 23:59:59",
    "location_ids": ["6252001"],
    "age_groups": ["AGE_18_24", "AGE_25_34"],
    "gender": "GENDER_FEMALE",
}

AD_RAW = {
    "ad_id": "ad1",
    "ad_name": "Video Ad",
    "adgroup_id": "ag1",
    "campaign_id": "cmp1",
    "operation_status": "ENABLE",
    "ad_text": "Buy now",
    "call_to_action": "SHOP_NOW",
    "landing_page_url": "https://example.com",
    "video_id": "v123",
}

REPORT_ROW = {
    "dimensions": {"campaign_id": "cmp1", "stat_time_day": "2026-06-01 00:00:00"},
    "metrics": {
        "spend": "12.34",
        "impressions": "1000",
        "clicks": "50",
        "ctr": "5.0",
        "cpc": "0.25",
        "cpm": "12.34",
        "reach": "800",
        "frequency": "1.25",
        "conversion": "3",
        "video_play_actions": "600",
    },
}


def envelope(data: dict) -> dict:
    return {"code": 0, "message": "OK", "request_id": "req-1", "data": data}


def list_envelope(rows: list[dict], page: int = 1, total_page: int = 1, total_number: int | None = None) -> dict:
    return envelope(
        {
            "list": rows,
            "page_info": {
                "page": page,
                "page_size": 20,
                "total_number": total_number if total_number is not None else len(rows),
                "total_page": total_page,
            },
        }
    )


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient()

    def campaigns_pager(method, path, kwargs):
        page = int(kwargs.get("params", {}).get("page", 1))
        return list_envelope([CAMPAIGN_RAW], page=page, total_page=3, total_number=60)

    fake.add("GET", "campaign/get/", campaigns_pager)
    fake.add("POST", "campaign/create/", envelope({"campaign_id": "cmp1"}))
    fake.add("POST", "campaign/status/update/", envelope({"campaign_ids": ["cmp1"]}))
    fake.add("POST", "campaign/update/", envelope({"campaign_id": "cmp1"}))

    fake.add("GET", "adgroup/get/", list_envelope([ADGROUP_RAW]))
    fake.add("POST", "adgroup/create/", envelope({"adgroup_id": "ag1"}))
    fake.add("POST", "adgroup/status/update/", envelope({"adgroup_ids": ["ag1"]}))
    fake.add("POST", "adgroup/update/", envelope({"adgroup_id": "ag1"}))

    fake.add("GET", "ad/get/", list_envelope([AD_RAW]))
    fake.add("POST", "ad/create/", envelope({"ad_ids": ["ad1"], "creatives": [{"ad_id": "ad1"}]}))
    fake.add("POST", "ad/status/update/", envelope({"ad_ids": ["ad1"]}))
    fake.add("POST", "ad/update/", envelope({"ad_ids": ["ad1"]}))

    fake.add(
        "POST",
        "file/image/ad/upload/",
        envelope({"image_id": "img123", "image_url": "https://cdn.tiktok.example/img123.png"}),
    )
    fake.add("POST", "file/video/ad/upload/", envelope([{"video_id": "v456"}]))

    fake.add("GET", "report/integrated/get/", list_envelope([REPORT_ROW]))
    return fake


@pytest.fixture
def tiktok_adapter(fake_http: FakeHttpClient) -> TikTokAdsAdapter:
    return TikTokAdsAdapter(
        credentials={"access_token": "test-token", "advertiser_id": "adv1"},
        http_client=fake_http,
    )


@pytest.fixture
def adapter(tiktok_adapter: TikTokAdsAdapter) -> TikTokAdsAdapter:
    return tiktok_adapter


@pytest.fixture
def sample_campaign_id() -> str:
    return "cmp1"


@pytest.fixture
def sample_ad_group_id() -> str:
    return "ag1"


@pytest.fixture
def sample_ad_id() -> str:
    return "ad1"


@pytest.fixture
def campaign_draft() -> AdCampaign:
    return AdCampaign(name="Summer Sale", objective=AdObjective.TRAFFIC, daily_budget=Decimal("50"))


@pytest.fixture
def ad_group_draft() -> AdGroup:
    return AdGroup(
        campaign_id="cmp1",
        name="Women 18-34",
        daily_budget=Decimal("20"),
        targeting=AdTargeting(age_min=18, age_max=34, genders=["female"]),
    )


@pytest.fixture
def ad_draft() -> Ad:
    return Ad(
        ad_group_id="ag1",
        name="Video Ad",
        creative=AdCreative(body="Buy now", landing_url="https://example.com"),
        extra={"video_id": "v123"},
    )


class TestTikTokAdsContract(AdsContractTests):
    """TikTok Ads must pass the shared AdsPort contract."""

    @pytest.fixture
    def adapter(self, tiktok_adapter: TikTokAdsAdapter) -> TikTokAdsAdapter:
        # Override the contract's placeholder fixture with the fake-backed adapter.
        return tiktok_adapter


class TestCheckResponse:
    """Envelope error code mapping."""

    def test_success_returns_data(self):
        assert check_response(envelope({"list": []})) == {"list": []}

    def test_success_without_data_returns_empty_dict(self):
        assert check_response({"code": 0, "message": "OK"}) == {}

    @pytest.mark.parametrize("code", [40100, 40101, 40102, 40104, 40105])
    def test_auth_codes(self, code: int):
        with pytest.raises(AuthenticationError):
            check_response({"code": code, "message": "Access token invalid"})

    @pytest.mark.parametrize("code", [40016, 40033])
    def test_rate_limit_codes(self, code: int):
        with pytest.raises(RateLimitError):
            check_response({"code": code, "message": "Slow down"})

    def test_rate_limit_by_message(self):
        with pytest.raises(RateLimitError):
            check_response({"code": 40999, "message": "Too Many Requests, please retry"})
        with pytest.raises(RateLimitError):
            check_response({"code": 40999, "message": "API Rate Limit exceeded"})

    @pytest.mark.parametrize("code", [40001, 40002, 40007])
    def test_validation_codes(self, code: int):
        with pytest.raises(ValidationError):
            check_response({"code": code, "message": "Invalid parameter"})

    def test_other_4xxxx_is_permanent(self):
        with pytest.raises(PermanentProviderError):
            check_response({"code": 40300, "message": "Not allowed"})

    def test_5xxxx_is_provider_error(self):
        with pytest.raises(ProviderError):
            check_response({"code": 50000, "message": "Internal error"})

    def test_error_includes_code_and_message(self):
        with pytest.raises(ProviderError, match=r"50000.*Internal error"):
            check_response({"code": 50000, "message": "Internal error"})


class TestClientRequests:
    """Outgoing request shape: headers, params, bodies."""

    def test_access_token_header_on_get(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        adapter.list_campaigns()
        call = fake_http.last_call()
        assert call.method == "GET"
        assert call.kwargs["headers"] == {"Access-Token": "test-token"}

    def test_access_token_header_on_post(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        adapter.set_campaign_status("cmp1", "paused")
        post_call = next(c for c in fake_http.calls if c.path == "campaign/status/update/")
        assert post_call.kwargs["headers"] == {"Access-Token": "test-token"}
        assert post_call.kwargs["json"]["advertiser_id"] == "adv1"
        assert post_call.kwargs["json"]["operation_status"] == "DISABLE"

    def test_get_filtering_is_json_encoded(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        adapter.get_campaign("cmp1")
        params = fake_http.last_call().kwargs["params"]
        assert params["advertiser_id"] == "adv1"
        assert json.loads(params["filtering"]) == {"campaign_ids": ["cmp1"]}

    def test_create_ad_sends_creative_with_video_id(
        self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient, ad_draft: Ad
    ):
        adapter.create_ad(ad_draft)
        create_call = next(c for c in fake_http.calls if c.path == "ad/create/")
        creative = create_call.kwargs["json"]["creatives"][0]
        assert creative["ad_name"] == "Video Ad"
        assert creative["ad_text"] == "Buy now"
        assert creative["landing_page_url"] == "https://example.com"
        assert creative["video_id"] == "v123"

    def test_create_ad_group_sends_targeting(
        self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient, ad_group_draft: AdGroup
    ):
        adapter.create_ad_group(ad_group_draft)
        create_call = next(c for c in fake_http.calls if c.path == "adgroup/create/")
        body = create_call.kwargs["json"]
        assert body["age_groups"] == ["AGE_18_24", "AGE_25_34"]
        assert body["gender"] == "GENDER_FEMALE"
        assert body["budget_mode"] == "BUDGET_MODE_DAY"
        assert body["budget"] == 20.0


class TestBudgetMapping:
    """budget_mode selection from normalized budget fields."""

    def test_daily_budget(self):
        payload = campaign_to_tiktok_payload({"name": "c", "daily_budget": Decimal("50")})
        assert payload["budget_mode"] == "BUDGET_MODE_DAY"
        assert payload["budget"] == 50.0

    def test_lifetime_budget(self):
        payload = campaign_to_tiktok_payload({"name": "c", "lifetime_budget": Decimal("500")})
        assert payload["budget_mode"] == "BUDGET_MODE_TOTAL"
        assert payload["budget"] == 500.0

    def test_no_budget_defaults_to_infinite(self):
        payload = campaign_to_tiktok_payload({"name": "c"})
        assert payload["budget_mode"] == "BUDGET_MODE_INFINITE"
        assert "budget" not in payload

    def test_partial_update_without_budget_omits_budget_mode(self):
        payload = campaign_to_tiktok_payload({"name": "c"}, partial=True)
        assert "budget_mode" not in payload


class TestAgeBrackets:
    """age_min/age_max ↔ TikTok age group brackets."""

    def test_range_to_groups(self):
        assert age_range_to_groups(18, 34) == ["AGE_18_24", "AGE_25_34"]

    def test_range_to_groups_partial_overlap(self):
        assert age_range_to_groups(16, 40) == ["AGE_13_17", "AGE_18_24", "AGE_25_34", "AGE_35_44"]

    def test_range_to_groups_open_ends(self):
        assert age_range_to_groups(55, None) == ["AGE_55_100"]
        assert age_range_to_groups(None, 17) == ["AGE_13_17"]

    def test_groups_to_range(self):
        assert age_groups_to_range(["AGE_18_24", "AGE_25_34"]) == (18, 34)
        assert age_groups_to_range(["AGE_55_100"]) == (55, 100)

    def test_groups_to_range_empty(self):
        assert age_groups_to_range([]) == (None, None)

    def test_roundtrip_via_adapter(self, adapter: TikTokAdsAdapter):
        ad_group = adapter.get_ad_group("ag1")
        assert ad_group.targeting is not None
        assert ad_group.targeting.age_min == 18
        assert ad_group.targeting.age_max == 34
        assert ad_group.targeting.genders == ["female"]
        assert ad_group.targeting.extra["location_ids"] == ["6252001"]


class TestInsightsMapping:
    """Report row → universal AdInsights."""

    def test_report_row_maps_to_universal_fields(self):
        insights = insights_from_tiktok(REPORT_ROW, AdInsightsLevel.CAMPAIGN)
        assert insights.entity_id == "cmp1"
        assert insights.level == AdInsightsLevel.CAMPAIGN
        assert insights.spend == Decimal("12.34")
        assert isinstance(insights.spend, Decimal)
        assert insights.impressions == 1000
        assert insights.clicks == 50
        assert insights.reach == 800
        assert insights.video_views == 600
        assert insights.ctr == 5.0
        assert insights.frequency == 1.25
        assert insights.cpc == Decimal("0.25")
        assert insights.conversions == 3.0
        assert insights.date_start == datetime(2026, 6, 1)
        assert insights.date_stop == datetime(2026, 6, 1)

    def test_get_insights_builds_report_request(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        rows = adapter.get_insights(AdInsightsLevel.CAMPAIGN, entity_id="cmp1")
        assert len(rows) == 1
        params = fake_http.last_call().kwargs["params"]
        assert params["data_level"] == "AUCTION_CAMPAIGN"
        assert json.loads(params["dimensions"]) == ["campaign_id", "stat_time_day"]
        assert json.loads(params["filtering"]) == [
            {"field_name": "campaign_ids", "filter_type": "IN", "filter_value": ["cmp1"]}
        ]
        assert params["start_date"] < params["end_date"]


class TestPagination:
    """Page-number cursor pagination."""

    def test_first_page_has_more(self, adapter: TikTokAdsAdapter):
        result = adapter.list_campaigns()
        assert result.has_more is True
        assert result.cursor == "2"
        assert result.total == 60

    def test_cursor_requests_that_page(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        result = adapter.list_campaigns(cursor="2")
        assert fake_http.last_call().kwargs["params"]["page"] == 2
        assert result.cursor == "3"

    def test_last_page_has_no_cursor(self, adapter: TikTokAdsAdapter):
        result = adapter.list_campaigns(cursor="3")
        assert result.has_more is False
        assert result.cursor is None


class TestCreativeUpload:
    """CreativeUploadCapability: media uploads + inline creative preparation."""

    def test_supports_creative_upload(self, adapter: TikTokAdsAdapter):
        assert adapter.supports(CreativeUploadCapability) is True

    def test_upload_image_by_url(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        asset = AdMediaAsset(media_type=AdMediaType.IMAGE, url="https://example.com/pic.png", filename="pic.png")
        media = adapter.upload_media(asset)

        call = next(c for c in fake_http.calls if c.path == "file/image/ad/upload/")
        body = call.kwargs["json"]
        assert body["advertiser_id"] == "adv1"
        assert body["upload_type"] == "UPLOAD_BY_URL"
        assert body["image_url"] == "https://example.com/pic.png"
        assert body["file_name"] == "pic.png"

        assert media.id == "img123"
        assert media.media_type == AdMediaType.IMAGE
        assert media.url == "https://cdn.tiktok.example/img123.png"
        assert media.extra["image_id"] == "img123"

    def test_upload_video_by_file_bytes(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        content = b"fake-video-bytes"
        asset = AdMediaAsset(media_type=AdMediaType.VIDEO, content=content, filename="clip.mp4")
        media = adapter.upload_media(asset)

        call = next(c for c in fake_http.calls if c.path == "file/video/ad/upload/")
        assert call.kwargs["files"] == {"video_file": ("clip.mp4", content)}
        form = call.kwargs["data"]
        assert form["advertiser_id"] == "adv1"
        assert form["upload_type"] == "UPLOAD_BY_FILE"
        assert form["video_signature"] == hashlib.md5(content).hexdigest()
        assert form["file_name"] == "clip.mp4"

        assert media.id == "v456"
        assert media.media_type == AdMediaType.VIDEO

    def test_upload_without_source_is_rejected(self, adapter: TikTokAdsAdapter):
        with pytest.raises(ValidationError):
            adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE))

    def test_create_creative_merges_video_id(self, adapter: TikTokAdsAdapter):
        creative = AdCreative(body="Buy now", landing_url="https://example.com")
        media = UploadedAdMedia(id="v456", media_type=AdMediaType.VIDEO)
        prepared = adapter.create_creative(creative, media)
        assert prepared.extra["video_id"] == "v456"
        assert prepared.body == "Buy now"

    def test_create_creative_appends_image_ids(self, adapter: TikTokAdsAdapter):
        creative = AdCreative(body="Buy now")
        first = adapter.create_creative(creative, UploadedAdMedia(id="img1", media_type=AdMediaType.IMAGE))
        assert first.extra["image_ids"] == ["img1"]
        second = adapter.create_creative(first, UploadedAdMedia(id="img2", media_type=AdMediaType.IMAGE))
        assert second.extra["image_ids"] == ["img1", "img2"]

    def test_create_creative_without_media_returns_creative_unchanged(self, adapter: TikTokAdsAdapter):
        creative = AdCreative(body="Buy now", extra={"video_id": "v456"})
        assert adapter.create_creative(creative) == creative

    def test_create_ad_picks_video_id_from_creative_extra(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        ad = Ad(
            ad_group_id="ag1",
            name="Video Ad",
            creative=AdCreative(body="Buy now", extra={"video_id": "v456"}),
        )
        adapter.create_ad(ad)
        create_call = next(c for c in fake_http.calls if c.path == "ad/create/")
        creative = create_call.kwargs["json"]["creatives"][0]
        assert creative["video_id"] == "v456"


class TestStatusMapping:
    """Status write mapping and invalid statuses."""

    def test_set_status_rejects_unmappable_status(self, adapter: TikTokAdsAdapter):
        with pytest.raises(ValidationError):
            adapter.set_campaign_status("cmp1", "archived")

    def test_set_status_sends_enable(self, adapter: TikTokAdsAdapter, fake_http: FakeHttpClient):
        adapter.set_ad_status("ad1", "active")
        post_call = next(c for c in fake_http.calls if c.path == "ad/status/update/")
        assert post_call.kwargs["json"]["operation_status"] == "ENABLE"
        assert post_call.kwargs["json"]["ad_ids"] == ["ad1"]


class TestTikTokAdsOAuth:
    """TikTok for Business portal OAuth flow tests."""

    @pytest.fixture
    def oauth_credentials(self) -> dict:
        return {"app_id": "test_app_id", "app_secret": "test_app_secret"}

    @pytest.fixture
    def oauth_adapter(self, oauth_credentials) -> TikTokAdsAdapter:
        return TikTokAdsAdapter(credentials=oauth_credentials)

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with TikTok for Business"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["app_id", "app_secret"]
        # Business API scopes are configured on the developer app, not the URL.
        assert manifest.auth.oauth.scopes == []

    def test_access_token_not_required_advertiser_id_still_required(self):
        access_token_field = next(f for f in manifest.auth.required_fields if f.name == "access_token")
        assert access_token_field.required is False
        advertiser_id_field = next(f for f in manifest.auth.required_fields if f.name == "advertiser_id")
        assert advertiser_id_field.required is True

    def test_supports_oauth_capability(self, oauth_adapter: TikTokAdsAdapter):
        assert oauth_adapter.supports(OAuthCapability) is True

    def test_adapter_constructible_with_only_app_credentials(self, oauth_adapter: TikTokAdsAdapter):
        assert oauth_adapter._app_id == "test_app_id"
        assert oauth_adapter._app_secret == "test_app_secret"

    def test_validate_credentials_accepts_app_credentials_without_token(self):
        adapter = TikTokAdsAdapter(
            credentials={"app_id": "test_app_id", "app_secret": "test_app_secret", "advertiser_id": "adv1"},
        )
        assert adapter.validate_credentials() is True

    def test_validate_credentials_keeps_token_behavior(self):
        adapter = TikTokAdsAdapter(credentials={"access_token": "test-token", "advertiser_id": "adv1"})
        assert adapter.validate_credentials() is True
        adapter = TikTokAdsAdapter(credentials={"advertiser_id": "adv1"})
        assert adapter.validate_credentials() is False

    def test_get_authorize_url(self, oauth_adapter: TikTokAdsAdapter):
        url = oauth_adapter.get_authorize_url("https://example.com/callback", state="xyz789")
        assert url.startswith("https://business-api.tiktok.com/portal/auth?")
        params = parse_qs(urlparse(url).query)
        assert params["app_id"] == ["test_app_id"]
        assert params["state"] == ["xyz789"]
        assert params["redirect_uri"] == ["https://example.com/callback"]

    def test_exchange_code_for_token(self, oauth_credentials):
        fake = FakeHttpClient()
        fake.add(
            "POST",
            "oauth2/access_token/",
            envelope({"access_token": "long-term-token", "advertiser_ids": ["adv1", "adv2"], "scope": [4]}),
        )
        adapter = TikTokAdsAdapter(credentials=oauth_credentials, http_client=fake)

        tokens = adapter.exchange_code_for_token("auth-code-123", "https://example.com/callback")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "oauth2/access_token/"
        assert call.kwargs["json"] == {
            "app_id": "test_app_id",
            "secret": "test_app_secret",
            "auth_code": "auth-code-123",
        }
        assert tokens.access_token == "long-term-token"
        assert tokens.refresh_token == ""
        assert tokens.expires_in is None
        assert tokens.extra["credentials"] == {
            "access_token": "long-term-token",
            "app_id": "test_app_id",
            "app_secret": "test_app_secret",
        }
        # Surfaced so the caller can pick the advertiser_id credential.
        assert tokens.extra["advertiser_ids"] == ["adv1", "adv2"]

    def test_exchange_error_routes_through_check_response(self, oauth_credentials):
        fake = FakeHttpClient()
        fake.add("POST", "oauth2/access_token/", {"code": 40105, "message": "Auth code is invalid"})
        adapter = TikTokAdsAdapter(credentials=oauth_credentials, http_client=fake)
        with pytest.raises(AuthenticationError, match="Auth code is invalid"):
            adapter.exchange_code_for_token("bad-code", "https://example.com/callback")

    def test_refresh_token_is_unsupported(self, oauth_adapter: TikTokAdsAdapter):
        with pytest.raises(UnsupportedFeatureError, match="long-term"):
            oauth_adapter.refresh_token("anything")
