"""
LinkedIn Ads adapter unit tests + contract tests.

All tests run against a FakeHttpClient with canned Marketing API responses.
Hierarchy under test: AdCampaign ↔ LinkedIn campaign group, AdGroup ↔
LinkedIn campaign, Ad ↔ LinkedIn creative. Creates return the new id in the
``x-restli-id`` header of a raw response (direct_response=True).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    AdTargeting,
)
from bapp_connectors.core.errors import ValidationError
from bapp_connectors.providers.ads.linkedin.adapter import LinkedInAdsAdapter
from bapp_connectors.providers.ads.linkedin.manifest import manifest
from bapp_connectors.providers.ads.linkedin.mappers import (
    STATUS_READ_MAP,
    STATUS_WRITE_MAP,
    ad_from_creative,
    campaign_group_patch,
    creative_patch,
    decimal_to_money,
    insights_from_row,
    money_to_decimal,
    status_from_linkedin,
    status_to_linkedin,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

ACCOUNT_ID = "512345678"
ACCOUNT_URN_ENC = "urn%3Ali%3AsponsoredAccount%3A512345678"
CREATIVE_URN_ENC = "urn%3Ali%3AsponsoredCreative%3A501"
NEW_CREATIVE_URN_ENC = "urn%3Ali%3AsponsoredCreative%3A601"

# 2026-06-01T00:00:00Z / 2026-06-30T00:00:00Z in epoch milliseconds.
START_MS = 1780272000000
END_MS = 1782777600000

GROUP_RAW = {
    "id": 101,
    "account": f"urn:li:sponsoredAccount:{ACCOUNT_ID}",
    "name": "Brand Awareness",
    "status": "ACTIVE",
    "totalBudget": {"amount": "500", "currencyCode": "USD"},
    "runSchedule": {"start": START_MS, "end": END_MS},
}

CAMPAIGN_RAW = {
    "id": 301,
    "account": f"urn:li:sponsoredAccount:{ACCOUNT_ID}",
    "campaignGroup": "urn:li:sponsoredCampaignGroup:101",
    "name": "US Traffic",
    "status": "ACTIVE",
    "type": "SPONSORED_UPDATES",
    "costType": "CPC",
    "unitCost": {"amount": "2.5", "currencyCode": "USD"},
    "dailyBudget": {"amount": "25.5", "currencyCode": "USD"},
    "totalBudget": {"amount": "300", "currencyCode": "USD"},
    "runSchedule": {"start": START_MS},
    "targetingCriteria": {
        "include": {"and": [{"or": {"urn:li:adTargetingFacet:locations": ["urn:li:geo:103644278"]}}]}
    },
}

CREATIVE_RAW = {
    "id": "urn:li:sponsoredCreative:501",
    "campaign": "urn:li:sponsoredCampaign:301",
    "intendedStatus": "ACTIVE",
    "content": {"reference": "urn:li:share:900"},
}

ANALYTICS_ROW = {
    "impressions": 1000,
    "clicks": 50,
    "costInLocalCurrency": "12.5",
    "externalWebsiteConversions": 3,
    "dateRange": {
        "start": {"year": 2026, "month": 6, "day": 1},
        "end": {"year": 2026, "month": 6, "day": 30},
    },
    "pivotValues": ["urn:li:sponsoredCampaignGroup:101"],
}


@dataclass
class FakeRestliResponse:
    """Raw response stand-in for direct_response=True creates (id in x-restli-id)."""

    headers: dict = field(default_factory=dict)
    ok: bool = True
    status_code: int = 201


def envelope(elements: list[dict], next_token: str | None = None) -> dict:
    result: dict = {"elements": elements}
    if next_token:
        result["metadata"] = {"nextPageToken": next_token}
    return result


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient()
    # Order matters: substring rules — specific paths (get/partial-update) before
    # bare collection creates, and the account rule (a prefix of everything) last.
    fake.add("GET", "adCampaignGroups?q=search", envelope([GROUP_RAW]))
    fake.add("GET", "adCampaignGroups/201", {**GROUP_RAW, "id": 201})
    fake.add("GET", "adCampaignGroups/101", GROUP_RAW)
    fake.add("POST", "adCampaignGroups/101", {})
    fake.add("POST", "adCampaignGroups", FakeRestliResponse(headers={"x-restli-id": "201"}))
    fake.add("GET", "adCampaigns?q=search", envelope([CAMPAIGN_RAW]))
    fake.add("GET", "adCampaigns/401", {**CAMPAIGN_RAW, "id": 401})
    fake.add("GET", "adCampaigns/301", CAMPAIGN_RAW)
    fake.add("POST", "adCampaigns/301", {})
    fake.add("POST", "adCampaigns", FakeRestliResponse(headers={"x-restli-id": "401"}))
    fake.add("GET", "creatives?q=criteria", envelope([CREATIVE_RAW]))
    fake.add("GET", f"creatives/{NEW_CREATIVE_URN_ENC}", {**CREATIVE_RAW, "id": "urn:li:sponsoredCreative:601"})
    fake.add("GET", f"creatives/{CREATIVE_URN_ENC}", CREATIVE_RAW)
    fake.add("POST", f"creatives/{CREATIVE_URN_ENC}", {})
    fake.add("POST", "creatives", FakeRestliResponse(headers={"x-restli-id": "urn:li:sponsoredCreative:601"}))
    fake.add("GET", "adAnalytics", {"elements": [ANALYTICS_ROW]})
    fake.add("GET", f"adAccounts/{ACCOUNT_ID}", {"id": int(ACCOUNT_ID), "name": "Test Account"})
    return fake


@pytest.fixture
def adapter(fake_http: FakeHttpClient) -> LinkedInAdsAdapter:
    return LinkedInAdsAdapter(
        credentials={"access_token": "test-token", "ad_account_id": ACCOUNT_ID},
        http_client=fake_http,
    )


class TestLinkedInAdsContract(AdsContractTests):
    """Run all AdsPort contract tests against the LinkedIn adapter."""

    @pytest.fixture
    def adapter(self, fake_http: FakeHttpClient) -> LinkedInAdsAdapter:
        return LinkedInAdsAdapter(
            credentials={"access_token": "test-token", "ad_account_id": ACCOUNT_ID},
            http_client=fake_http,
        )

    @pytest.fixture
    def sample_campaign_id(self) -> str:
        return "101"

    @pytest.fixture
    def sample_ad_group_id(self) -> str:
        return "301"

    @pytest.fixture
    def sample_ad_id(self) -> str:
        return "501"

    @pytest.fixture
    def campaign_draft(self) -> AdCampaign:
        return AdCampaign(name="Contract Group", lifetime_budget=Decimal("100"))

    @pytest.fixture
    def ad_group_draft(self) -> AdGroup:
        return AdGroup(
            campaign_id="101",
            name="Contract Campaign",
            daily_budget=Decimal("10"),
            bid_amount=Decimal("2"),
            targeting=AdTargeting(extra={"geo_urns": ["urn:li:geo:103644278"]}),
        )

    @pytest.fixture
    def ad_draft(self) -> Ad:
        return Ad(ad_group_id="301", name="Contract Ad", creative=AdCreative(id="urn:li:share:123"))


class TestHierarchyMapping:
    """AdCampaign ↔ campaign group, AdGroup ↔ campaign, Ad ↔ creative."""

    def test_campaign_is_campaign_group(self, adapter, fake_http):
        campaign = adapter.get_campaign("101")
        assert fake_http.last_call().path == f"adAccounts/{ACCOUNT_ID}/adCampaignGroups/101"
        assert campaign.id == "101"
        assert campaign.name == "Brand Awareness"
        assert campaign.status == AdEntityStatus.ACTIVE
        assert campaign.lifetime_budget == Decimal("500")
        assert campaign.currency == "USD"
        assert campaign.start_time == datetime(2026, 6, 1, tzinfo=UTC)
        assert campaign.end_time == datetime(2026, 6, 30, tzinfo=UTC)

    def test_ad_group_is_campaign(self, adapter, fake_http):
        ad_group = adapter.get_ad_group("301")
        assert fake_http.last_call().path == f"adAccounts/{ACCOUNT_ID}/adCampaigns/301"
        assert ad_group.id == "301"
        assert ad_group.campaign_id == "101"  # tail of the campaignGroup URN
        assert ad_group.daily_budget == Decimal("25.5")
        assert ad_group.lifetime_budget == Decimal("300")
        assert ad_group.bid_amount == Decimal("2.5")
        assert ad_group.targeting is not None
        assert ad_group.targeting.extra["geo_urns"] == ["urn:li:geo:103644278"]
        assert ad_group.targeting.countries == []  # geo URNs are not ISO countries

    def test_ad_is_creative(self, adapter, fake_http):
        ad = adapter.get_ad("501")
        assert fake_http.last_call().path == f"adAccounts/{ACCOUNT_ID}/creatives/{CREATIVE_URN_ENC}"
        assert ad.id == "501"
        assert ad.ad_group_id == "301"  # tail of the campaign URN
        assert ad.name == "501"  # creatives have no name; id doubles as name
        assert ad.creative is not None
        assert ad.creative.id == "urn:li:sponsoredCreative:501"
        assert ad.creative.extra["content_reference"] == "urn:li:share:900"

    def test_create_campaign_posts_campaign_group_payload(self, adapter, fake_http):
        created = adapter.create_campaign(AdCampaign(name="New Group", lifetime_budget=Decimal("100"), currency="EUR"))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaignGroups"))
        payload = create_call.kwargs["json"]
        assert payload["account"] == f"urn:li:sponsoredAccount:{ACCOUNT_ID}"
        assert payload["name"] == "New Group"
        assert payload["status"] == "PAUSED"  # drafts default to PAUSED
        assert payload["totalBudget"] == {"amount": "100", "currencyCode": "EUR"}
        assert isinstance(payload["runSchedule"]["start"], int)  # epoch ms, defaults to now
        assert created.id == "201"  # id read from the x-restli-id header, then re-fetched

    def test_create_ad_group_posts_campaign_payload(self, adapter, fake_http):
        adapter.create_ad_group(AdGroup(campaign_id="101", name="New Campaign", daily_budget=Decimal("10")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaigns"))
        payload = create_call.kwargs["json"]
        assert payload["campaignGroup"] == "urn:li:sponsoredCampaignGroup:101"
        assert payload["type"] == "SPONSORED_UPDATES"
        assert payload["costType"] == "CPC"
        assert payload["unitCost"] == {"amount": "2", "currencyCode": "USD"}  # default bid
        assert payload["dailyBudget"] == {"amount": "10", "currencyCode": "USD"}
        assert payload["locale"] == {"country": "US", "language": "en"}
        # No draft targeting: falls back to the default geo.
        assert payload["targetingCriteria"] == {
            "include": {"and": [{"or": {"urn:li:adTargetingFacet:locations": ["urn:li:geo:103644278"]}}]}
        }

    def test_create_ad_group_passes_draft_geo_urns_through(self, adapter, fake_http):
        adapter.create_ad_group(
            AdGroup(
                campaign_id="101",
                name="Geo Campaign",
                bid_amount=Decimal("1.5"),
                targeting=AdTargeting(extra={"geo_urns": ["urn:li:geo:900", "urn:li:geo:901"]}),
            )
        )
        create_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaigns"))
        payload = create_call.kwargs["json"]
        assert payload["unitCost"] == {"amount": "1.5", "currencyCode": "USD"}
        locations = payload["targetingCriteria"]["include"]["and"][0]["or"]["urn:li:adTargetingFacet:locations"]
        assert locations == ["urn:li:geo:900", "urn:li:geo:901"]


class TestMoneyMapping:
    def test_money_to_decimal(self):
        assert money_to_decimal({"amount": "10.5", "currencyCode": "USD"}) == Decimal("10.5")
        assert money_to_decimal(None) is None
        assert money_to_decimal({}) is None
        assert money_to_decimal({"amount": ""}) is None

    def test_decimal_to_money(self):
        assert decimal_to_money(Decimal("10.5"), "RON") == {"amount": "10.5", "currencyCode": "RON"}
        assert decimal_to_money(2) == {"amount": "2", "currencyCode": "USD"}

    def test_round_trip(self):
        money = decimal_to_money(Decimal("123.45"), "EUR")
        assert money_to_decimal(money) == Decimal("123.45")


class TestStatusMapping:
    def test_read_map(self):
        assert status_from_linkedin("ACTIVE") == AdEntityStatus.ACTIVE
        assert status_from_linkedin("PAUSED") == AdEntityStatus.PAUSED
        assert status_from_linkedin("ARCHIVED") == AdEntityStatus.ARCHIVED
        assert status_from_linkedin("CANCELED") == AdEntityStatus.ENDED
        assert status_from_linkedin("CANCELLED") == AdEntityStatus.ENDED
        assert status_from_linkedin("DRAFT") == AdEntityStatus.DRAFT
        assert status_from_linkedin("PENDING_DELETION") == AdEntityStatus.DELETED
        assert status_from_linkedin("REMOVED") == AdEntityStatus.DELETED
        assert status_from_linkedin("SOMETHING_NEW") == AdEntityStatus.UNKNOWN

    def test_write_map_round_trip(self):
        for status in (AdEntityStatus.ACTIVE, AdEntityStatus.PAUSED, AdEntityStatus.ARCHIVED):
            assert STATUS_READ_MAP[STATUS_WRITE_MAP[status]] == status

    def test_deleted_writes_as_archived(self):
        """LinkedIn has no hard delete — DELETED maps to ARCHIVED."""
        assert status_to_linkedin(AdEntityStatus.DELETED) == "ARCHIVED"

    def test_unmappable_status_raises(self):
        with pytest.raises(ValidationError):
            status_to_linkedin(AdEntityStatus.ENDED)

    def test_set_campaign_status_sends_partial_update_patch(self, adapter, fake_http):
        adapter.set_campaign_status("101", AdEntityStatus.DELETED)
        update_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaignGroups/101"))
        assert update_call.kwargs["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
        assert update_call.kwargs["json"] == {"patch": {"$set": {"status": "ARCHIVED"}}}

    def test_set_ad_status_sends_intended_status(self, adapter, fake_http):
        adapter.set_ad_status("501", AdEntityStatus.PAUSED)
        update_call = next(
            c for c in fake_http.calls if c.method == "POST" and c.path.endswith(f"creatives/{CREATIVE_URN_ENC}")
        )
        assert update_call.kwargs["headers"]["X-RestLi-Method"] == "PARTIAL_UPDATE"
        assert update_call.kwargs["json"] == {"patch": {"$set": {"intendedStatus": "PAUSED"}}}


class TestPartialUpdate:
    def test_update_campaign_maps_normalized_fields(self, adapter, fake_http):
        adapter.update_campaign("101", {"name": "Renamed", "lifetime_budget": Decimal("750")})
        update_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaignGroups/101"))
        assert update_call.kwargs["json"] == {
            "patch": {
                "$set": {"name": "Renamed", "totalBudget": {"amount": "750", "currencyCode": "USD"}},
            },
        }

    def test_update_ad_group_maps_budgets_and_bid(self, adapter, fake_http):
        adapter.update_ad_group("301", {"daily_budget": Decimal("30"), "bid_amount": Decimal("3.5")})
        update_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("adCampaigns/301"))
        assert update_call.kwargs["json"]["patch"]["$set"] == {
            "dailyBudget": {"amount": "30", "currencyCode": "USD"},
            "unitCost": {"amount": "3.5", "currencyCode": "USD"},
        }

    def test_unsupported_update_field_raises(self, adapter):
        with pytest.raises(ValidationError):
            adapter.update_campaign("101", {"objective": "traffic"})
        with pytest.raises(ValidationError):
            adapter.update_ad("501", {"name": "New name"})

    def test_empty_patch_raises(self):
        with pytest.raises(ValidationError):
            campaign_group_patch({})
        with pytest.raises(ValidationError):
            creative_patch({})


class TestCreativeReference:
    """LinkedIn creatives reference organic posts — a content reference URN is required."""

    def test_create_ad_without_content_reference_raises(self, adapter):
        with pytest.raises(ValidationError):
            adapter.create_ad(Ad(ad_group_id="301", name="No reference"))
        with pytest.raises(ValidationError):
            # A bare creative id that is not a URN is not a usable post reference.
            adapter.create_ad(Ad(ad_group_id="301", name="Bad id", creative=AdCreative(id="12345")))

    def test_create_ad_with_post_urn_as_creative_id(self, adapter, fake_http):
        ad = adapter.create_ad(Ad(ad_group_id="301", name="Share ad", creative=AdCreative(id="urn:li:share:123")))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("creatives"))
        assert create_call.kwargs["json"] == {
            "campaign": "urn:li:sponsoredCampaign:301",
            "intendedStatus": "PAUSED",
            "content": {"reference": "urn:li:share:123"},
        }
        assert ad.id == "601"  # URN from x-restli-id, tail re-fetched

    def test_create_ad_with_extra_content_reference(self, adapter, fake_http):
        adapter.create_ad(Ad(ad_group_id="301", name="Extra ref", extra={"content_reference": "urn:li:ugcPost:77"}))
        create_call = next(c for c in fake_http.calls if c.method == "POST" and c.path.endswith("creatives"))
        assert create_call.kwargs["json"]["content"] == {"reference": "urn:li:ugcPost:77"}

    def test_ad_from_creative_preserves_reference(self):
        ad = ad_from_creative(CREATIVE_RAW)
        assert ad.creative is not None
        assert ad.creative.extra["content_reference"] == "urn:li:share:900"
        assert ad.status == AdEntityStatus.ACTIVE  # from intendedStatus


class TestInsights:
    def test_insights_row_mapping_with_derived_metrics(self):
        insights = insights_from_row(ANALYTICS_ROW, AdInsightsLevel.CAMPAIGN)
        assert insights.entity_id == "101"  # tail of pivotValues[0]
        assert insights.impressions == 1000
        assert insights.clicks == 50
        assert insights.spend == Decimal("12.5")
        assert insights.conversions == 3.0
        # ctr/cpc/cpm are not exposed by LinkedIn — derived from the counters.
        assert insights.ctr == 5.0
        assert insights.cpc == Decimal("0.25")
        assert insights.cpm == Decimal("12.5")
        assert insights.date_start == datetime(2026, 6, 1)
        assert insights.date_stop == datetime(2026, 6, 30)

    def test_insights_missing_metrics_are_none(self):
        insights = insights_from_row({"impressions": 10}, AdInsightsLevel.AD)
        assert insights.impressions == 10
        assert insights.clicks is None
        assert insights.spend is None
        assert insights.conversions is None
        assert insights.ctr is None  # not derivable without clicks
        assert insights.cpc is None
        assert insights.cpm is None
        assert insights.entity_id == ""

    def test_insights_no_division_by_zero(self):
        insights = insights_from_row({"impressions": 0, "clicks": 0, "costInLocalCurrency": "0"}, AdInsightsLevel.AD)
        assert insights.ctr is None
        assert insights.cpc is None
        assert insights.cpm is None

    def test_get_insights_builds_restli_query(self, adapter, fake_http):
        rows = adapter.get_insights(
            AdInsightsLevel.CAMPAIGN,
            entity_id="101",
            since=datetime(2026, 6, 1),
            until=datetime(2026, 6, 30),
        )
        path = fake_http.last_call().path
        assert path.startswith("adAnalytics?")
        assert "q=analytics" in path
        assert "pivot=CAMPAIGN_GROUP" in path  # our campaign level = LinkedIn campaign group
        assert "dateRange=(start:(year:2026,month:6,day:1),end:(year:2026,month:6,day:30))" in path
        assert "timeGranularity=ALL" in path
        assert f"accounts=List({ACCOUNT_URN_ENC})" in path
        assert "campaignGroups=List(urn%3Ali%3AsponsoredCampaignGroup%3A101)" in path
        assert "fields=impressions,clicks,costInLocalCurrency,externalWebsiteConversions,dateRange,pivotValues" in path
        assert rows and rows[0].level == AdInsightsLevel.CAMPAIGN

    def test_get_insights_pivots_per_level(self, adapter, fake_http):
        adapter.get_insights(AdInsightsLevel.AD_GROUP, entity_id="301")
        path = fake_http.last_call().path
        assert "pivot=CAMPAIGN" in path
        assert "campaigns=List(urn%3Ali%3AsponsoredCampaign%3A301)" in path

        adapter.get_insights(AdInsightsLevel.AD, entity_id="501")
        path = fake_http.last_call().path
        assert "pivot=CREATIVE" in path
        assert "creatives=List(urn%3Ali%3AsponsoredCreative%3A501)" in path

        adapter.get_insights(AdInsightsLevel.ACCOUNT)
        assert "pivot=ACCOUNT" in fake_http.last_call().path

    def test_get_insights_defaults_to_last_30_days(self, adapter, fake_http):
        adapter.get_insights(AdInsightsLevel.ACCOUNT)
        path = fake_http.last_call().path
        assert "dateRange=(start:(year:" in path
        assert ",end:(year:" in path


class TestQueryEncodingAndHeaders:
    def test_list_ad_groups_encodes_campaign_group_filter(self, adapter, fake_http):
        adapter.list_ad_groups(campaign_id="101")
        path = fake_http.last_call().path
        assert "q=search" in path
        assert "search=(campaignGroup:(values:List(urn%3Ali%3AsponsoredCampaignGroup%3A101)))" in path

    def test_list_ads_encodes_campaign_filter(self, adapter, fake_http):
        adapter.list_ads(ad_group_id="301")
        path = fake_http.last_call().path
        assert "q=criteria" in path
        assert "campaigns=List(urn%3Ali%3AsponsoredCampaign%3A301)" in path

    def test_restli_headers_on_every_call(self, adapter, fake_http):
        adapter.list_campaigns()
        headers = fake_http.last_call().kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["X-Restli-Protocol-Version"] == "2.0.0"
        assert headers["LinkedIn-Version"] == "202405"  # setting default

    def test_linkedin_version_setting_respected(self, fake_http):
        adapter = LinkedInAdsAdapter(
            credentials={"access_token": "test-token", "ad_account_id": ACCOUNT_ID},
            http_client=fake_http,
            config={"linkedin_version": "202501"},
        )
        adapter.list_campaigns()
        assert fake_http.last_call().kwargs["headers"]["LinkedIn-Version"] == "202501"

    def test_pagination_cursor(self, adapter, fake_http):
        fake_http.responses.insert(0, ("GET", "adCampaignGroups?q=search", envelope([GROUP_RAW], "tok_next")))
        result = adapter.list_campaigns()
        assert result.cursor == "tok_next"
        assert result.has_more is True

        adapter.list_campaigns(cursor="tok_next")
        assert "pageToken=tok_next" in fake_http.last_call().path


class TestConnection:
    def test_connection(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "Test Account" in result.message
        assert ACCOUNT_ID in result.message


OAUTH_SCOPES = ["rw_ads", "r_ads_reporting"]


class TestLinkedInOAuth:
    def make_oauth_adapter(self, fake: FakeHttpClient | None = None) -> LinkedInAdsAdapter:
        return LinkedInAdsAdapter(
            credentials={"client_id": "cid_123", "client_secret": "cs_456", "ad_account_id": ACCOUNT_ID},
            http_client=fake or FakeHttpClient(),
        )

    def test_oauth_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with LinkedIn Ads"
        assert [f.name for f in manifest.auth.oauth.credential_fields] == ["client_id", "client_secret"]
        assert manifest.auth.oauth.scopes == OAUTH_SCOPES

    def test_access_token_not_required_in_manifest(self):
        token_field = next(f for f in manifest.auth.required_fields if f.name == "access_token")
        assert token_field.required is False
        assert token_field.sensitive is True
        account_field = next(f for f in manifest.auth.required_fields if f.name == "ad_account_id")
        assert account_field.required is True

    def test_supports_oauth_capability(self, adapter):
        assert adapter.supports(OAuthCapability) is True

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True  # access_token + ad_account_id
        assert self.make_oauth_adapter().validate_credentials() is True  # client_id + client_secret
        empty = LinkedInAdsAdapter(credentials={"ad_account_id": ACCOUNT_ID}, http_client=FakeHttpClient())
        assert empty.validate_credentials() is False

    def test_get_authorize_url(self):
        url = self.make_oauth_adapter().get_authorize_url("https://example.com/cb", state="xyz789")
        assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
        query = parse_qs(urlparse(url).query)
        assert query["response_type"] == ["code"]
        assert query["client_id"] == ["cid_123"]
        assert query["redirect_uri"] == ["https://example.com/cb"]
        assert query["state"] == ["xyz789"]
        assert query["scope"] == ["rw_ads r_ads_reporting"]  # space-joined

    def test_exchange_code_for_token(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/v2/accessToken", {"access_token": "AT", "expires_in": 5184000})
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("the_code", "https://example.com/cb")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.path == "https://www.linkedin.com/oauth/v2/accessToken"
        assert call.kwargs["data"] == {
            "grant_type": "authorization_code",
            "code": "the_code",
            "redirect_uri": "https://example.com/cb",
            "client_id": "cid_123",
            "client_secret": "cs_456",
        }
        assert tokens.access_token == "AT"
        assert tokens.refresh_token == ""  # tolerated: LinkedIn may not issue one
        assert tokens.expires_in == 5184000
        assert tokens.extra["credentials"] == {
            "access_token": "AT",
            "client_id": "cid_123",
            "client_secret": "cs_456",
        }

    def test_exchange_code_keeps_refresh_token_when_issued(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/v2/accessToken", {"access_token": "AT", "refresh_token": "RT"})
        tokens = self.make_oauth_adapter(fake).exchange_code_for_token("code", "https://example.com/cb")
        assert tokens.refresh_token == "RT"

    def test_refresh_token(self):
        fake = FakeHttpClient()
        fake.add("POST", "oauth/v2/accessToken", {"access_token": "AT2", "expires_in": 3600})
        tokens = self.make_oauth_adapter(fake).refresh_token("RT")

        data = fake.last_call().kwargs["data"]
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "RT"
        assert data["client_id"] == "cid_123"
        assert data["client_secret"] == "cs_456"
        assert tokens.access_token == "AT2"
        assert tokens.refresh_token == "RT"  # absent in the response — current one kept


AD_ACCOUNTS_SEARCH = {
    "elements": [
        {"id": 512345678, "name": "Test Account", "currency": "USD", "status": "ACTIVE"},
        {"id": 900000001, "name": "Second Account", "currency": "EUR", "status": "DRAFT"},
    ],
}


class TestListAdAccounts:
    """Connect-flow helper: the adAccounts?q=search finder."""

    def test_returns_picker_rows(self, adapter, fake_http):
        fake_http.responses.insert(0, ("GET", "adAccounts?q=search", AD_ACCOUNTS_SEARCH))
        accounts = adapter.list_ad_accounts()
        assert accounts == [
            {"ad_account_id": "512345678", "name": "Test Account", "currency": "USD", "status": "ACTIVE"},
            {"ad_account_id": "900000001", "name": "Second Account", "currency": "EUR", "status": "DRAFT"},
        ]

    def test_uses_stored_token_and_restli_headers(self, adapter, fake_http):
        fake_http.responses.insert(0, ("GET", "adAccounts?q=search", AD_ACCOUNTS_SEARCH))
        adapter.list_ad_accounts()
        call = fake_http.last_call()
        assert call.method == "GET"
        assert call.path == "adAccounts?q=search"
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-token"
        assert call.kwargs["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
        assert call.kwargs["headers"]["LinkedIn-Version"] == "202405"

    def test_explicit_token_overrides_credential(self, adapter, fake_http):
        fake_http.responses.insert(0, ("GET", "adAccounts?q=search", AD_ACCOUNTS_SEARCH))
        adapter.list_ad_accounts(access_token="FRESH_TOKEN")
        headers = fake_http.last_call().kwargs["headers"]
        assert headers["Authorization"] == "Bearer FRESH_TOKEN"
        assert headers["X-Restli-Protocol-Version"] == "2.0.0"

    def test_empty_elements_returns_empty_list(self):
        fake = FakeHttpClient()
        fake.add("GET", "adAccounts?q=search", {"elements": []})
        adapter = LinkedInAdsAdapter(
            credentials={"access_token": "test-token", "ad_account_id": ACCOUNT_ID},
            http_client=fake,
        )
        assert adapter.list_ad_accounts() == []
