"""
Pinterest Ads adapter unit tests — contract suite + provider-specific behavior.

All HTTP is faked with canned Pinterest API v5 responses: bookmark-paginated
list envelopes ``{"items": [...], "bookmark": ...}``, bulk-style write
responses (list bodies of one object in, ``{"items": [{...}]}`` out), and
flat analytics rows keyed by column names.
"""

from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from bapp_connectors.core.capabilities import OAuthCapability
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
from bapp_connectors.providers.ads.pinterest import PinterestAdsAdapter
from bapp_connectors.providers.ads.pinterest.manifest import manifest
from bapp_connectors.providers.ads.pinterest.mappers import (
    OBJECTIVE_TO_PINTEREST,
    age_buckets_to_range,
    age_range_to_buckets,
    campaign_from_pinterest,
    decimal_to_micro,
    insights_from_pinterest,
    micro_to_decimal,
    status_from_pinterest,
    status_to_pinterest,
    targeting_from_pinterest,
    targeting_to_pinterest,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

ACCOUNT_ID = "549755885175"

# ── Canned Pinterest payloads ──

CAMPAIGN_RAW = {
    "id": "cmp1",
    "ad_account_id": ACCOUNT_ID,
    "name": "Summer Pins",
    "status": "ACTIVE",
    "objective_type": "CONSIDERATION",
    "daily_spend_cap": 25000000,  # micro-currency: 25.00
    "start_time": 1780272000,  # 2026-06-01T00:00:00Z
}

ADGROUP_RAW = {
    "id": "ag1",
    "ad_account_id": ACCOUNT_ID,
    "campaign_id": "cmp1",
    "name": "Women 18-44",
    "status": "ACTIVE",
    "budget_in_micro_currency": 10000000,  # 10.00
    "budget_type": "DAILY",
    "bid_in_micro_currency": 500000,  # 0.50
    "start_time": 1780272000,
    "targeting_spec": {
        "GEO": ["RO", "HU"],
        "AGE_BUCKET": ["18-24", "25-34", "35-44"],
        "GENDER": ["female"],
    },
}

AD_RAW = {
    "id": "ad1",
    "ad_account_id": ACCOUNT_ID,
    "ad_group_id": "ag1",
    "campaign_id": "cmp1",
    "name": "Pin Ad",
    "status": "ACTIVE",
    "creative_type": "REGULAR",
    "pin_id": "pin123",
    "destination_url": "https://example.com/landing",
}

CAMPAIGN_ANALYTICS_ROW = {
    "CAMPAIGN_ID": "cmp1",
    "DATE": "2026-06-01",
    "SPEND_IN_DOLLAR": "12.34",
    "IMPRESSION_1": "1000",
    "CLICKTHROUGH_1": "50",
    "CTR": "5.0",
    "ECPC_IN_DOLLAR": "0.25",
    "TOTAL_CONVERSIONS": "3",
    "VIDEO_MRC_VIEWS_1": "40",
    "TOTAL_ENGAGEMENT": "77",
}

ADGROUP_ANALYTICS_ROW = {**CAMPAIGN_ANALYTICS_ROW, "AD_GROUP_ID": "ag1"}
AD_ANALYTICS_ROW = {**CAMPAIGN_ANALYTICS_ROW, "AD_ID": "ad1"}
ACCOUNT_ANALYTICS_ROW = {
    "SPEND_IN_DOLLAR": "99.00",
    "IMPRESSION_1": "5000",
    "CLICKTHROUGH_1": "200",
}


def bookmark_envelope(rows: list[dict], bookmark: str | None = None) -> dict:
    return {"items": rows, "bookmark": bookmark}


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient()
    # Order matters: substring rules — analytics and single-object rules go
    # before their list-edge prefixes, and the bare ad_accounts/{id} rule last.
    fake.add("GET", "campaigns/analytics", [CAMPAIGN_ANALYTICS_ROW])
    fake.add("GET", "ad_groups/analytics", [ADGROUP_ANALYTICS_ROW])
    fake.add("GET", "ads/analytics", [AD_ANALYTICS_ROW])
    fake.add("GET", f"{ACCOUNT_ID}/analytics", [ACCOUNT_ANALYTICS_ROW])

    fake.add("GET", "campaigns/cmp1", CAMPAIGN_RAW)
    fake.add("GET", "campaigns", bookmark_envelope([CAMPAIGN_RAW]))
    # POST responses exercise the {"data": ...} item wrapper; PATCH the bare item shape.
    fake.add("POST", "campaigns", {"items": [{"data": {**CAMPAIGN_RAW, "id": "cmp_new"}}]})
    fake.add("PATCH", "campaigns", {"items": [{**CAMPAIGN_RAW, "status": "PAUSED"}]})

    fake.add("GET", "ad_groups/ag1", ADGROUP_RAW)
    fake.add("GET", "ad_groups", bookmark_envelope([ADGROUP_RAW]))
    fake.add("POST", "ad_groups", {"items": [{"data": {**ADGROUP_RAW, "id": "ag_new"}}]})
    fake.add("PATCH", "ad_groups", {"items": [{**ADGROUP_RAW, "status": "PAUSED"}]})

    fake.add("GET", "ads/ad1", AD_RAW)
    fake.add("GET", "ads", bookmark_envelope([AD_RAW]))
    fake.add("POST", "ads", {"items": [{"data": {**AD_RAW, "id": "ad_new"}}]})
    fake.add("PATCH", "ads", {"items": [{**AD_RAW, "status": "PAUSED"}]})

    fake.add("GET", f"ad_accounts/{ACCOUNT_ID}", {"id": ACCOUNT_ID, "name": "Test Account", "currency": "USD"})
    return fake


@pytest.fixture
def adapter(fake_http: FakeHttpClient) -> PinterestAdsAdapter:
    return PinterestAdsAdapter(
        credentials={"token": "test-token", "ad_account_id": ACCOUNT_ID},
        http_client=fake_http,
    )


class TestPinterestAdsContract(AdsContractTests):
    """Run all AdsPort contract tests against the Pinterest adapter."""

    @pytest.fixture
    def adapter(self, fake_http: FakeHttpClient) -> PinterestAdsAdapter:
        return PinterestAdsAdapter(
            credentials={"token": "test-token", "ad_account_id": ACCOUNT_ID},
            http_client=fake_http,
        )

    @pytest.fixture
    def sample_campaign_id(self) -> str:
        return "cmp1"

    @pytest.fixture
    def sample_ad_group_id(self) -> str:
        return "ag1"

    @pytest.fixture
    def sample_ad_id(self) -> str:
        return "ad1"

    @pytest.fixture
    def campaign_draft(self) -> AdCampaign:
        return AdCampaign(name="Contract Campaign", objective=AdObjective.TRAFFIC, daily_budget=Decimal("10"))

    @pytest.fixture
    def ad_group_draft(self) -> AdGroup:
        return AdGroup(
            campaign_id="cmp1",
            name="Contract Ad Group",
            daily_budget=Decimal("5"),
            targeting=AdTargeting(countries=["RO"], age_min=18),
        )

    @pytest.fixture
    def ad_draft(self) -> Ad:
        return Ad(ad_group_id="ag1", name="Contract Ad", creative=AdCreative(id="pin123"))


class TestMicroCurrency:
    """Budgets/bids cross the boundary as Decimals; Pinterest wants micro-currency ints."""

    def test_micro_round_trip(self):
        assert decimal_to_micro(Decimal("12.34")) == 12340000
        assert micro_to_decimal(12340000) == Decimal("12.34")
        assert micro_to_decimal(decimal_to_micro(Decimal("0.5"))) == Decimal("0.5")
        assert micro_to_decimal(None) is None

    def test_campaign_create_sends_micros_in_list_body(self, adapter, fake_http):
        adapter.create_campaign(AdCampaign(name="Budget", objective=AdObjective.TRAFFIC, daily_budget=Decimal("10")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and "campaigns" in c.path)
        body = create_call.kwargs["json"]
        assert isinstance(body, list) and len(body) == 1  # v5 bulk-style: list body of one object
        assert body[0]["daily_spend_cap"] == 10000000
        assert body[0]["objective_type"] == "CONSIDERATION"
        assert "status" not in body[0]  # UNKNOWN draft status is not written

    def test_ad_group_create_converts_budget_and_bid(self, adapter, fake_http):
        adapter.create_ad_group(
            AdGroup(campaign_id="cmp1", name="Bid", lifetime_budget=Decimal("100"), bid_amount=Decimal("1.25"))
        )
        create_call = next(c for c in fake_http.calls if c.method == "POST" and "ad_groups" in c.path)
        payload = create_call.kwargs["json"][0]
        assert payload["budget_in_micro_currency"] == 100000000
        assert payload["budget_type"] == "LIFETIME"
        assert payload["bid_in_micro_currency"] == 1250000

    def test_budget_read_converts_micros_to_decimal(self, adapter):
        campaign = adapter.get_campaign("cmp1")
        assert campaign.daily_budget == Decimal("25")
        ad_group = adapter.get_ad_group("ag1")
        assert ad_group.daily_budget == Decimal("10")
        assert ad_group.lifetime_budget is None
        assert ad_group.bid_amount == Decimal("0.5")


class TestAgeBuckets:
    def test_age_range_to_buckets(self):
        assert age_range_to_buckets(18, 44) == ["18-24", "25-34", "35-44"]
        assert age_range_to_buckets(50, None) == ["50-54", "55-64", "65+"]
        assert age_range_to_buckets(None, 30) == ["18-24", "25-34"]
        assert age_range_to_buckets(None, None) == ["18-24", "25-34", "35-44", "45-49", "50-54", "55-64", "65+"]

    def test_age_buckets_to_range(self):
        assert age_buckets_to_range(["25-34", "35-44"]) == (25, 44)
        assert age_buckets_to_range(["55-64", "65+"]) == (55, None)  # open-ended bucket → age_max None
        assert age_buckets_to_range([]) == (None, None)
        assert age_buckets_to_range(["not-a-bucket"]) == (None, None)

    def test_targeting_round_trip(self):
        spec = targeting_to_pinterest(AdTargeting(countries=["RO", "HU"], age_min=18, age_max=44, genders=["female"]))
        assert spec == {"GEO": ["RO", "HU"], "AGE_BUCKET": ["18-24", "25-34", "35-44"], "GENDER": ["female"]}
        targeting = targeting_from_pinterest(spec)
        assert targeting.countries == ["RO", "HU"]
        assert targeting.age_min == 18
        assert targeting.age_max == 44
        assert targeting.genders == ["female"]

    def test_targeting_extra_keys_preserved(self):
        targeting = targeting_from_pinterest({"GEO": ["RO"], "INTEREST": ["948"]})
        assert targeting.extra == {"INTEREST": ["948"]}
        assert targeting_to_pinterest(targeting)["INTEREST"] == ["948"]


class TestStatusMapping:
    def test_status_read_map(self):
        assert status_from_pinterest("ACTIVE") == AdEntityStatus.ACTIVE
        assert status_from_pinterest("PAUSED") == AdEntityStatus.PAUSED
        assert status_from_pinterest("ARCHIVED") == AdEntityStatus.ARCHIVED
        assert status_from_pinterest("SOMETHING_NEW") == AdEntityStatus.UNKNOWN

    def test_deleted_writes_as_archived(self):
        # Pinterest has no hard delete — DELETED archives the entity.
        assert status_to_pinterest(AdEntityStatus.DELETED) == "ARCHIVED"
        assert status_to_pinterest(AdEntityStatus.ARCHIVED) == "ARCHIVED"

    def test_unmappable_status_raises(self):
        with pytest.raises(ValidationError):
            status_to_pinterest(AdEntityStatus.PENDING_REVIEW)

    def test_set_campaign_status_deleted_sends_archived(self, adapter, fake_http):
        campaign = adapter.set_campaign_status("cmp1", AdEntityStatus.DELETED)
        patch_call = next(c for c in fake_http.calls if c.method == "PATCH" and "campaigns" in c.path)
        assert patch_call.kwargs["json"] == [{"id": "cmp1", "status": "ARCHIVED"}]
        # The PATCH response maps straight back to a DTO — no re-fetch.
        assert campaign.status == AdEntityStatus.PAUSED
        assert not any(c.method == "GET" for c in fake_http.calls)


class TestObjectiveMapping:
    def test_objective_read_map(self):
        assert campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "AWARENESS"}).objective == (
            AdObjective.AWARENESS
        )
        assert campaign_from_pinterest(CAMPAIGN_RAW).objective == AdObjective.TRAFFIC
        assert campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "VIDEO_VIEW"}).objective == (
            AdObjective.VIDEO_VIEWS
        )
        assert campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "WEB_CONVERSION"}).objective == (
            AdObjective.SALES
        )
        assert campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "CATALOG_SALES"}).objective == (
            AdObjective.SALES
        )
        assert campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "SOMETHING_NEW"}).objective == (
            AdObjective.OTHER
        )

    def test_raw_objective_kept_in_extra(self):
        campaign = campaign_from_pinterest({**CAMPAIGN_RAW, "objective_type": "CATALOG_SALES"})
        assert campaign.extra["objective_type"] == "CATALOG_SALES"

    def test_every_normalized_objective_writes(self):
        for objective in AdObjective:
            assert OBJECTIVE_TO_PINTEREST[objective]
        assert OBJECTIVE_TO_PINTEREST[AdObjective.ENGAGEMENT] == "CONSIDERATION"
        assert OBJECTIVE_TO_PINTEREST[AdObjective.SALES] == "WEB_CONVERSION"


class TestAds:
    def test_create_ad_without_pin_raises(self, adapter):
        with pytest.raises(ValidationError, match=r"[Pp]in"):
            adapter.create_ad(Ad(ad_group_id="ag1", name="No pin"))

    def test_create_ad_sends_pin_id_and_creative_type(self, adapter, fake_http):
        adapter.create_ad(Ad(ad_group_id="ag1", name="Promoted", creative=AdCreative(id="pin123")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and "ads" in c.path)
        payload = create_call.kwargs["json"][0]
        assert payload["pin_id"] == "pin123"
        assert payload["creative_type"] == "REGULAR"
        assert payload["ad_group_id"] == "ag1"

    def test_create_ad_pin_id_from_extra(self, adapter, fake_http):
        adapter.create_ad(Ad(ad_group_id="ag1", name="Promoted", extra={"pin_id": "pin777"}))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and "ads" in c.path)
        assert create_call.kwargs["json"][0]["pin_id"] == "pin777"

    def test_ad_from_pinterest_maps_pin_into_creative(self, adapter):
        ad = adapter.get_ad("ad1")
        assert ad.creative is not None
        assert ad.creative.id == "pin123"
        assert ad.creative.landing_url == "https://example.com/landing"
        assert ad.campaign_id == "cmp1"


class TestInsights:
    def test_analytics_row_mapping(self):
        insights = insights_from_pinterest(CAMPAIGN_ANALYTICS_ROW, AdInsightsLevel.CAMPAIGN)
        assert insights.entity_id == "cmp1"
        assert insights.impressions == 1000
        assert insights.clicks == 50
        assert insights.spend == Decimal("12.34")
        assert insights.ctr == 5.0
        assert insights.cpc == Decimal("0.25")
        assert insights.conversions == 3.0
        assert insights.video_views == 40
        assert insights.date_start == datetime(2026, 6, 1)
        assert insights.date_stop == datetime(2026, 6, 1)
        assert insights.extra == {"TOTAL_ENGAGEMENT": "77"}  # unmapped columns preserved

    def test_spend_in_micro_dollar_tolerated(self):
        row = {"CAMPAIGN_ID": "cmp1", "SPEND_IN_MICRO_DOLLAR": 12340000, "IMPRESSION_1": "10"}
        insights = insights_from_pinterest(row, AdInsightsLevel.CAMPAIGN)
        assert insights.spend == Decimal("12.34")

    def test_missing_metrics_are_none(self):
        insights = insights_from_pinterest({"AD_ID": "ad1", "IMPRESSION_1": "10"}, AdInsightsLevel.AD)
        assert insights.impressions == 10
        assert insights.spend is None
        assert insights.conversions is None
        assert insights.video_views is None

    def test_get_insights_params(self, adapter, fake_http):
        adapter.get_insights(
            AdInsightsLevel.CAMPAIGN, entity_id="cmp1", since=datetime(2026, 6, 1), until=datetime(2026, 6, 30)
        )
        call = fake_http.last_call()
        assert call.path == f"ad_accounts/{ACCOUNT_ID}/campaigns/analytics"
        assert call.kwargs["params"]["start_date"] == "2026-06-01"
        assert call.kwargs["params"]["end_date"] == "2026-06-30"
        assert call.kwargs["params"]["campaign_ids"] == "cmp1"
        assert call.kwargs["params"]["granularity"] == "TOTAL"
        assert call.kwargs["params"]["columns"] == (
            "SPEND_IN_DOLLAR,IMPRESSION_1,CLICKTHROUGH_1,CTR,ECPC_IN_DOLLAR,TOTAL_CONVERSIONS"
        )

    def test_get_insights_levels_route_to_endpoints(self, adapter, fake_http):
        adapter.get_insights(AdInsightsLevel.ACCOUNT)
        assert fake_http.last_call().path == f"ad_accounts/{ACCOUNT_ID}/analytics"
        adapter.get_insights(AdInsightsLevel.AD_GROUP, entity_id="ag1")
        assert fake_http.last_call().path == f"ad_accounts/{ACCOUNT_ID}/ad_groups/analytics"
        adapter.get_insights(AdInsightsLevel.AD, entity_id="ad1")
        assert fake_http.last_call().path == f"ad_accounts/{ACCOUNT_ID}/ads/analytics"

    def test_get_insights_defaults_to_last_30_days(self, adapter, fake_http):
        rows = adapter.get_insights(AdInsightsLevel.ACCOUNT)
        params = fake_http.last_call().kwargs["params"]
        start = datetime.strptime(params["start_date"], "%Y-%m-%d")
        end = datetime.strptime(params["end_date"], "%Y-%m-%d")
        assert (end - start).days == 30
        assert rows and rows[0].level == AdInsightsLevel.ACCOUNT


class TestPaginationAndFiltering:
    def test_bookmark_pagination(self, adapter, fake_http):
        fake_http.responses.insert(0, ("GET", "campaigns", bookmark_envelope([CAMPAIGN_RAW], bookmark="bm2")))
        result = adapter.list_campaigns()
        assert result.cursor == "bm2"
        assert result.has_more is True

        page_two = adapter.list_campaigns(cursor="bm2")
        assert fake_http.last_call().kwargs["params"]["bookmark"] == "bm2"
        assert page_two.items

    def test_no_bookmark_means_no_more_pages(self, adapter):
        result = adapter.list_campaigns()
        assert result.cursor is None
        assert result.has_more is False

    def test_list_ad_groups_filters_by_campaign(self, adapter, fake_http):
        adapter.list_ad_groups(campaign_id="cmp1")
        assert fake_http.last_call().kwargs["params"]["campaign_ids"] == "cmp1"

    def test_list_ads_filters_by_ad_group(self, adapter, fake_http):
        adapter.list_ads(ad_group_id="ag1")
        assert fake_http.last_call().kwargs["params"]["ad_group_ids"] == "ag1"

    def test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "Test Account" in result.message
        assert ACCOUNT_ID in result.message


OAUTH_SCOPES = ["ads:read", "ads:write"]


class TestPinterestAdsOAuth:
    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> PinterestAdsAdapter:
        return PinterestAdsAdapter(
            credentials={"client_id": "cid_123", "client_secret": "csecret_456", "ad_account_id": ACCOUNT_ID},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Pinterest Ads"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["client_id", "client_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "token")
        assert token_field.required is False
        account_field = next(f for f in manifest.auth.required_fields if f.name == "ad_account_id")
        assert account_field.required is True

    def test_supports_oauth_capability(self, adapter):
        assert adapter.supports(OAuthCapability) is True

    def test_validate_credentials(self):
        assert self.make_oauth_adapter().validate_credentials() is True  # client pair only
        no_token = PinterestAdsAdapter(credentials={"ad_account_id": ACCOUNT_ID}, http_client=FakeHttpClient())
        assert no_token.validate_credentials() is False

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.pinterest.com/oauth/?")
        query = parse_qs(urlparse(url).query)
        assert query["client_id"] == ["cid_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["response_type"] == ["code"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == ["ads:read,ads:write"]

    def test_exchange_code_for_token_uses_basic_auth(self):
        fake = FakeHttpClient()
        fake.add(
            "POST",
            "oauth/token",
            {"access_token": "AT", "refresh_token": "RT", "expires_in": 2592000, "token_type": "bearer"},
        )
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "oauth/token"
        expected = base64.b64encode(b"cid_123:csecret_456").decode()
        assert call.kwargs["headers"]["Authorization"] == f"Basic {expected}"
        assert call.kwargs["data"] == {
            "grant_type": "authorization_code",
            "code": "the_code",
            "redirect_uri": "https://example.com/cb",
        }
        assert tokens.access_token == "AT"
        assert tokens.refresh_token == "RT"
        assert tokens.expires_in == 2592000
        assert tokens.extra["credentials"] == {
            "token": "AT",
            "client_id": "cid_123",
            "client_secret": "csecret_456",
        }

    def test_refresh_token_keeps_incoming_token_when_omitted(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/token", {"access_token": "AT2", "expires_in": 2592000, "token_type": "bearer"})
        tokens = self.make_oauth_adapter(fake).refresh_token("RT_OLD")

        call = fake.last_call()
        expected = base64.b64encode(b"cid_123:csecret_456").decode()
        assert call.kwargs["headers"]["Authorization"] == f"Basic {expected}"
        assert call.kwargs["data"] == {"grant_type": "refresh_token", "refresh_token": "RT_OLD"}
        assert tokens.access_token == "AT2"
        assert tokens.refresh_token == "RT_OLD"  # response omitted it — keep the incoming one

    def test_refresh_token_prefers_rotated_token(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/token", {"access_token": "AT3", "refresh_token": "RT_NEW"})
        tokens = self.make_oauth_adapter(fake).refresh_token("RT_OLD")
        assert tokens.refresh_token == "RT_NEW"


AD_ACCOUNTS_LIST = {
    "items": [
        {"id": ACCOUNT_ID, "name": "Test Account", "currency": "USD", "country": "US"},
        {"id": "111111111111", "name": "Second Account", "currency": "EUR", "country": "RO"},
    ],
    "bookmark": None,
}


class TestListAdAccounts:
    """Connect-flow helper: GET ad_accounts with an optional Bearer override."""

    def make_helper_adapter(self, fake: FakeHttpClient) -> PinterestAdsAdapter:
        return PinterestAdsAdapter(credentials={"token": "stored-token"}, http_client=fake)

    def test_returns_picker_rows(self):
        fake = FakeHttpClient()
        fake.add("GET", "ad_accounts", AD_ACCOUNTS_LIST)
        accounts = self.make_helper_adapter(fake).list_ad_accounts()
        assert accounts == [
            {"ad_account_id": ACCOUNT_ID, "name": "Test Account", "currency": "USD", "country": "US"},
            {"ad_account_id": "111111111111", "name": "Second Account", "currency": "EUR", "country": "RO"},
        ]

    def test_stored_token_call_shape(self):
        fake = FakeHttpClient()
        fake.add("GET", "ad_accounts", AD_ACCOUNTS_LIST)
        self.make_helper_adapter(fake).list_ad_accounts()
        call = fake.last_call()
        assert call.method == "GET"
        assert call.path == "ad_accounts"
        assert call.kwargs["params"] == {"page_size": 25}
        assert call.kwargs["headers"] is None  # stored token: auth stays on the http client

    def test_explicit_token_sent_as_bearer_header_override(self):
        fake = FakeHttpClient()
        fake.add("GET", "ad_accounts", AD_ACCOUNTS_LIST)
        self.make_helper_adapter(fake).list_ad_accounts(access_token="FRESH_TOKEN")
        call = fake.last_call()
        assert call.kwargs["headers"] == {"Authorization": "Bearer FRESH_TOKEN"}
        assert call.kwargs["params"] == {"page_size": 25}

    def test_empty_items_returns_empty_list(self):
        fake = FakeHttpClient()
        fake.add("GET", "ad_accounts", {"items": [], "bookmark": None})
        assert self.make_helper_adapter(fake).list_ad_accounts() == []
