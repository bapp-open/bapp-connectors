"""
Google Ads adapter unit tests + contract tests.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from decimal import Decimal

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
)
from bapp_connectors.core.errors import PermanentProviderError, UnsupportedFeatureError, ValidationError
from bapp_connectors.providers.ads.google.adapter import GoogleAdsAdapter
from bapp_connectors.providers.ads.google.client import GoogleAdsClient, sanitize_customer_id
from bapp_connectors.providers.ads.google.errors import extract_ad_id, extract_resource_id
from bapp_connectors.providers.ads.google.manifest import manifest
from bapp_connectors.providers.ads.google.mappers import (
    campaign_from_row,
    decimal_to_micros,
    micros_to_decimal,
    status_to_google,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

CUSTOMER_ID = "1234567890"

CREDENTIALS = {
    "developer_token": "dev-token",
    "access_token": "access-token",
    "customer_id": "123-456-7890",
    "login_customer_id": "987-654-3210",
}

CUSTOMER = {
    "resourceName": f"customers/{CUSTOMER_ID}",
    "id": CUSTOMER_ID,
    "descriptiveName": "CB Soft",
    "currencyCode": "RON",
}


def _campaign_row(campaign_id: str, name: str, status: str = "ENABLED", channel: str = "SEARCH") -> dict:
    return {
        "campaign": {
            "resourceName": f"customers/{CUSTOMER_ID}/campaigns/{campaign_id}",
            "id": campaign_id,
            "name": name,
            "status": status,
            "advertisingChannelType": channel,
            "startDate": "2026-01-01",
            "endDate": "2026-12-31",
        },
        "campaignBudget": {"amountMicros": "25000000"},
        "customer": {"currencyCode": "RON"},
    }


def _ad_group_row(ad_group_id: str, campaign_id: str, name: str, status: str = "ENABLED") -> dict:
    return {
        "adGroup": {
            "resourceName": f"customers/{CUSTOMER_ID}/adGroups/{ad_group_id}",
            "id": ad_group_id,
            "name": name,
            "status": status,
            "cpcBidMicros": "500000",
        },
        "campaign": {"id": campaign_id},
    }


def _ad_row(ad_id: str, ad_group_id: str, campaign_id: str, status: str = "ENABLED") -> dict:
    return {
        "adGroupAd": {
            "resourceName": f"customers/{CUSTOMER_ID}/adGroupAds/{ad_group_id}~{ad_id}",
            "status": status,
            "ad": {
                "id": ad_id,
                "name": f"Ad {ad_id}",
                "finalUrls": ["https://example.com"],
                "responsiveSearchAd": {
                    "headlines": [{"text": "Headline"}, {"text": "Second headline"}],
                    "descriptions": [{"text": "Description"}],
                },
            },
        },
        "adGroup": {"id": ad_group_id},
        "campaign": {"id": campaign_id},
    }


CAMPAIGN_ROWS = {
    "111": _campaign_row("111", "Search campaign"),
    "222": _campaign_row("222", "Display campaign", status="PAUSED", channel="DISPLAY"),
    "999": _campaign_row("999", "New campaign", status="PAUSED"),
}

AD_GROUP_ROWS = {
    "333": _ad_group_row("333", "111", "Ad group one"),
    "444": _ad_group_row("444", "111", "New ad group", status="PAUSED"),
}

AD_ROWS = {
    "555": _ad_row("555", "333", "111"),
    "888": _ad_row("888", "333", "111", status="PAUSED"),
}

METRICS = {
    "impressions": "1000",
    "clicks": "50",
    "costMicros": "12500000",
    "ctr": 0.05,
    "averageCpc": "250000",
    "averageCpm": "12500",
    "conversions": 3.0,
    "conversionsValue": 150.0,
    "videoViews": "10",
}


def _where(query: str, field: str) -> str | None:
    match = re.search(rf"{re.escape(field)} = '?(\d+)'?", query)
    return match.group(1) if match else None


def _metrics_rows(query: str) -> list[dict]:
    row: dict = {
        "metrics": dict(METRICS),
        "customer": {"id": CUSTOMER_ID, "currencyCode": "RON"},
        "segments": {"date": "2026-06-01"},
    }
    if "FROM ad_group_ad" in query:
        row["adGroupAd"] = {"ad": {"id": _where(query, "ad_group_ad.ad.id") or "555"}}
    elif "FROM ad_group" in query:
        row["adGroup"] = {"id": _where(query, "ad_group.id") or "333"}
    elif "FROM campaign" in query:
        row["campaign"] = {"id": _where(query, "campaign.id") or "111"}
    return [row]


def _search_response(method: str, path: str, kwargs: dict) -> dict:
    """Dispatch canned GAQL rows based on the query's FROM and WHERE clauses."""
    query = kwargs["json"]["query"]
    if "metrics.impressions" in query:
        return {"results": _metrics_rows(query)}
    if "FROM ad_group_ad" in query:
        ad_id = _where(query, "ad_group_ad.ad.id")
        if ad_id:
            rows = [AD_ROWS[ad_id]] if ad_id in AD_ROWS else []
        else:
            group_id = _where(query, "ad_group.id")
            rows = [row for row in AD_ROWS.values() if group_id is None or row["adGroup"]["id"] == group_id]
        return {"results": rows}
    if "FROM ad_group" in query:
        group_id = _where(query, "ad_group.id")
        if group_id:
            rows = [AD_GROUP_ROWS[group_id]] if group_id in AD_GROUP_ROWS else []
        else:
            campaign_id = _where(query, "campaign.id")
            rows = [
                row for row in AD_GROUP_ROWS.values() if campaign_id is None or row["campaign"]["id"] == campaign_id
            ]
        return {"results": rows}
    if "FROM campaign" in query:
        campaign_id = _where(query, "campaign.id")
        if campaign_id:
            rows = [CAMPAIGN_ROWS[campaign_id]] if campaign_id in CAMPAIGN_ROWS else []
        else:
            rows = list(CAMPAIGN_ROWS.values())
        return {"results": rows}
    if "FROM customer" in query:
        return {"results": [{"customer": dict(CUSTOMER)}]}
    raise AssertionError(f"Unexpected GAQL query: {query}")


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient(base_url="https://googleads.googleapis.com/v17/")
    fake.add("POST", "googleAds:search", _search_response)
    fake.add(
        "POST",
        "campaignBudgets:mutate",
        {"results": [{"resourceName": f"customers/{CUSTOMER_ID}/campaignBudgets/777"}]},
    )
    fake.add("POST", "campaigns:mutate", {"results": [{"resourceName": f"customers/{CUSTOMER_ID}/campaigns/999"}]})
    fake.add("POST", "adGroups:mutate", {"results": [{"resourceName": f"customers/{CUSTOMER_ID}/adGroups/444"}]})
    fake.add(
        "POST", "adGroupAds:mutate", {"results": [{"resourceName": f"customers/{CUSTOMER_ID}/adGroupAds/333~888"}]}
    )
    fake.add("POST", "assets:mutate", {"results": [{"resourceName": f"customers/{CUSTOMER_ID}/assets/999"}]})
    return fake


@pytest.fixture
def adapter(fake_http) -> GoogleAdsAdapter:
    return GoogleAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


@pytest.fixture
def sample_campaign_id() -> str:
    return "111"


@pytest.fixture
def sample_ad_group_id() -> str:
    return "333"


@pytest.fixture
def sample_ad_id() -> str:
    return "555"


@pytest.fixture
def campaign_draft() -> AdCampaign:
    return AdCampaign(name="New campaign", objective=AdObjective.TRAFFIC, daily_budget=Decimal("10"))


@pytest.fixture
def ad_group_draft() -> AdGroup:
    return AdGroup(campaign_id="111", name="New ad group", bid_amount=Decimal("0.5"))


@pytest.fixture
def ad_draft() -> Ad:
    return Ad(
        ad_group_id="333",
        name="New ad",
        creative=AdCreative(title="Headline", body="Description", landing_url="https://example.com"),
    )


class TestGoogleAdsContract(AdsContractTests):
    """Run all ads contract tests for Google Ads."""

    @pytest.fixture
    def adapter(self, fake_http) -> GoogleAdsAdapter:
        return GoogleAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


class TestGoogleAdsMappers:
    """Google-specific mapper tests."""

    def test_micros_to_decimal(self):
        assert micros_to_decimal("25000000") == Decimal("25")
        assert micros_to_decimal(500000) == Decimal("0.5")
        assert micros_to_decimal(None) is None
        assert micros_to_decimal("") is None

    def test_decimal_to_micros(self):
        assert decimal_to_micros(Decimal("10")) == 10_000_000
        assert decimal_to_micros(Decimal("0.5")) == 500_000
        assert decimal_to_micros("1.25") == 1_250_000

    def test_status_write_map(self):
        assert status_to_google(AdEntityStatus.ACTIVE) == "ENABLED"
        assert status_to_google(AdEntityStatus.PAUSED) == "PAUSED"
        with pytest.raises(ValidationError):
            status_to_google(AdEntityStatus.ARCHIVED)
        with pytest.raises(ValidationError):
            status_to_google(AdEntityStatus.DELETED)

    def test_campaign_from_row(self):
        campaign = campaign_from_row(CAMPAIGN_ROWS["111"])
        assert campaign.id == "111"
        assert campaign.status is AdEntityStatus.ACTIVE
        assert campaign.objective is AdObjective.TRAFFIC  # SEARCH channel
        assert campaign.daily_budget == Decimal("25")
        assert campaign.currency == "RON"
        assert campaign.start_time == datetime(2026, 1, 1)
        assert campaign.extra["advertising_channel_type"] == "SEARCH"

    def test_campaign_from_row_display_channel(self):
        campaign = campaign_from_row(CAMPAIGN_ROWS["222"])
        assert campaign.status is AdEntityStatus.PAUSED
        assert campaign.objective is AdObjective.AWARENESS

    def test_extract_resource_id(self):
        assert extract_resource_id("customers/1/campaigns/42") == "42"
        assert extract_resource_id("customers/1/adGroupAds/123~456") == "123~456"

    def test_extract_ad_id(self):
        assert extract_ad_id("customers/1/adGroupAds/123~456") == "456"


class TestGoogleAdsClient:
    """Client-level tests: id sanitization and required headers."""

    def test_customer_id_dash_stripping(self):
        assert sanitize_customer_id("123-456-7890") == "1234567890"
        client = GoogleAdsClient(
            http_client=None,
            developer_token="dev-token",
            access_token="access-token",
            customer_id="123-456-7890",
            login_customer_id="987-654-3210",
        )
        assert client.customer_id == "1234567890"
        assert client.login_customer_id == "9876543210"

    def test_required_headers_present(self, adapter, fake_http):
        adapter.list_campaigns()
        call = fake_http.last_call()
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer access-token"
        assert headers["developer-token"] == "dev-token"
        assert headers["login-customer-id"] == "9876543210"
        assert call.path == f"customers/{CUSTOMER_ID}/googleAds:search"

    def test_login_customer_id_header_omitted_when_unset(self, fake_http):
        credentials = {k: v for k, v in CREDENTIALS.items() if k != "login_customer_id"}
        adapter = GoogleAdsAdapter(credentials=credentials, http_client=fake_http)
        adapter.list_campaigns()
        headers = fake_http.last_call().kwargs["headers"]
        assert "login-customer-id" not in headers


class TestGoogleAdsAdapter:
    """Adapter behaviour tests: mutate shapes, GAQL clauses, immutability rules."""

    def test_create_campaign_issues_budget_then_campaign_mutate(self, adapter, fake_http, campaign_draft):
        created = adapter.create_campaign(campaign_draft)
        mutate_paths = [call.path for call in fake_http.calls if ":mutate" in call.path]
        assert mutate_paths == [
            f"customers/{CUSTOMER_ID}/campaignBudgets:mutate",
            f"customers/{CUSTOMER_ID}/campaigns:mutate",
        ]
        budget_call = next(call for call in fake_http.calls if "campaignBudgets:mutate" in call.path)
        budget_op = budget_call.kwargs["json"]["operations"][0]["create"]
        assert budget_op["amountMicros"] == 10_000_000
        assert budget_op["name"] == "New campaign budget"
        assert budget_op["deliveryMethod"] == "STANDARD"
        assert budget_op["explicitlyShared"] is False

        campaign_call = next(call for call in fake_http.calls if "campaigns:mutate" in call.path)
        create_op = campaign_call.kwargs["json"]["operations"][0]["create"]
        assert create_op["campaignBudget"] == f"customers/{CUSTOMER_ID}/campaignBudgets/777"
        assert create_op["advertisingChannelType"] == "SEARCH"
        assert create_op["status"] == "PAUSED"
        assert create_op["manualCpc"] == {}
        assert created.id == "999"

    def test_create_campaign_default_budget(self, adapter, fake_http):
        adapter.create_campaign(AdCampaign(name="No budget", objective=AdObjective.VIDEO_VIEWS))
        budget_call = next(call for call in fake_http.calls if "campaignBudgets:mutate" in call.path)
        assert budget_call.kwargs["json"]["operations"][0]["create"]["amountMicros"] == 10_000_000
        campaign_call = next(call for call in fake_http.calls if "campaigns:mutate" in call.path)
        assert campaign_call.kwargs["json"]["operations"][0]["create"]["advertisingChannelType"] == "VIDEO"

    def test_get_insights_where_date_range(self, adapter, fake_http):
        insights = adapter.get_insights(
            AdInsightsLevel.CAMPAIGN,
            entity_id="111",
            since=datetime(2026, 1, 1),
            until=datetime(2026, 1, 31),
        )
        query = fake_http.last_call().kwargs["json"]["query"]
        assert "segments.date BETWEEN '2026-01-01' AND '2026-01-31'" in query
        assert "campaign.id = 111" in query
        assert "FROM campaign" in query
        assert len(insights) == 1
        row = insights[0]
        assert row.entity_id == "111"
        assert row.spend == Decimal("12.5")
        assert row.cpc == Decimal("0.25")
        assert row.currency == "RON"
        assert row.date_start == datetime(2026, 6, 1)

    def test_get_insights_account_level(self, adapter, fake_http):
        insights = adapter.get_insights(AdInsightsLevel.ACCOUNT)
        query = fake_http.last_call().kwargs["json"]["query"]
        assert "FROM customer" in query
        assert "WHERE" not in query
        assert insights[0].entity_id == CUSTOMER_ID

    def test_set_campaign_status_deleted_uses_remove(self, adapter, fake_http):
        campaign = adapter.set_campaign_status("111", AdEntityStatus.DELETED)
        mutate_call = next(call for call in fake_http.calls if "campaigns:mutate" in call.path)
        assert mutate_call.kwargs["json"]["operations"] == [{"remove": f"customers/{CUSTOMER_ID}/campaigns/111"}]
        assert campaign.status is AdEntityStatus.DELETED
        assert campaign.id == "111"

    def test_set_campaign_status_active_uses_update(self, adapter, fake_http):
        adapter.set_campaign_status("111", AdEntityStatus.ACTIVE)
        mutate_call = next(call for call in fake_http.calls if "campaigns:mutate" in call.path)
        operation = mutate_call.kwargs["json"]["operations"][0]
        assert operation["update"]["status"] == "ENABLED"
        assert operation["update"]["resourceName"] == f"customers/{CUSTOMER_ID}/campaigns/111"
        assert operation["updateMask"] == "status"

    def test_update_campaign_budget_change_rejected(self, adapter):
        with pytest.raises(ValidationError):
            adapter.update_campaign("111", {"daily_budget": Decimal("5")})

    def test_update_campaign_fields_and_mask(self, adapter, fake_http):
        adapter.update_campaign("111", {"name": "Renamed", "end_time": datetime(2026, 9, 30)})
        mutate_call = next(call for call in fake_http.calls if "campaigns:mutate" in call.path)
        operation = mutate_call.kwargs["json"]["operations"][0]
        assert operation["update"]["name"] == "Renamed"
        assert operation["update"]["endDate"] == "2026-09-30"
        assert operation["updateMask"] == "name,endDate"

    def test_create_ad_extracts_composite_id(self, adapter, fake_http, ad_draft):
        created = adapter.create_ad(ad_draft)
        assert created.id == "888"
        mutate_call = next(call for call in fake_http.calls if "adGroupAds:mutate" in call.path)
        create_op = mutate_call.kwargs["json"]["operations"][0]["create"]
        assert create_op["adGroup"] == f"customers/{CUSTOMER_ID}/adGroups/333"
        assert create_op["status"] == "PAUSED"
        assert create_op["ad"]["finalUrls"] == ["https://example.com"]
        assert create_op["ad"]["responsiveSearchAd"]["headlines"] == [{"text": "Headline"}]
        assert create_op["ad"]["responsiveSearchAd"]["descriptions"] == [{"text": "Description"}]

    def test_create_ad_requires_full_creative(self, adapter):
        with pytest.raises(ValidationError):
            adapter.create_ad(Ad(ad_group_id="333", name="No creative"))
        with pytest.raises(ValidationError):
            adapter.create_ad(Ad(ad_group_id="333", name="Partial", creative=AdCreative(title="Only title")))

    def test_update_ad_non_status_change_raises(self, adapter):
        with pytest.raises(ValidationError, match="immutable"):
            adapter.update_ad("555", {"name": "New name"})

    def test_update_ad_status_change_allowed(self, adapter, fake_http):
        ad = adapter.update_ad("555", {"status": AdEntityStatus.PAUSED})
        assert isinstance(ad, Ad)
        mutate_call = next(call for call in fake_http.calls if "adGroupAds:mutate" in call.path)
        operation = mutate_call.kwargs["json"]["operations"][0]
        assert operation["update"]["resourceName"] == f"customers/{CUSTOMER_ID}/adGroupAds/333~555"
        assert operation["updateMask"] == "status"

    def test_set_ad_status_deleted_uses_remove(self, adapter, fake_http):
        ad = adapter.set_ad_status("555", AdEntityStatus.DELETED)
        mutate_call = next(call for call in fake_http.calls if "adGroupAds:mutate" in call.path)
        assert mutate_call.kwargs["json"]["operations"] == [{"remove": f"customers/{CUSTOMER_ID}/adGroupAds/333~555"}]
        assert ad.status is AdEntityStatus.DELETED

    def test_get_campaign_not_found(self, adapter):
        with pytest.raises(PermanentProviderError):
            adapter.get_campaign("40404")

    def test_test_connection_includes_descriptive_name(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert "CB Soft" in result.message


IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class TestGoogleAdsCreativeUpload:
    """CreativeUploadCapability: image assets via assets:mutate, honest boundaries elsewhere."""

    def test_supports_creative_upload_capability(self, adapter):
        assert adapter.supports(CreativeUploadCapability) is True

    def test_upload_image_from_bytes(self, adapter, fake_http):
        asset = AdMediaAsset(media_type=AdMediaType.IMAGE, content=IMAGE_BYTES, filename="banner.png")
        uploaded = adapter.upload_media(asset)

        mutate_call = next(call for call in fake_http.calls if "assets:mutate" in call.path)
        assert mutate_call.path == f"customers/{CUSTOMER_ID}/assets:mutate"
        create_op = mutate_call.kwargs["json"]["operations"][0]["create"]
        assert create_op["name"] == "banner.png"
        assert create_op["type"] == "IMAGE"
        assert base64.b64decode(create_op["imageAsset"]["data"]) == IMAGE_BYTES

        assert uploaded.id == f"customers/{CUSTOMER_ID}/assets/999"
        assert uploaded.media_type is AdMediaType.IMAGE
        assert uploaded.extra["asset_id"] == "999"

    def test_upload_image_from_file_path(self, adapter, fake_http, tmp_path):
        image_file = tmp_path / "banner.png"
        image_file.write_bytes(IMAGE_BYTES)
        uploaded = adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE, file_path=str(image_file)))

        mutate_call = next(call for call in fake_http.calls if "assets:mutate" in call.path)
        create_op = mutate_call.kwargs["json"]["operations"][0]["create"]
        assert create_op["name"] == "image asset"  # no filename given
        assert base64.b64decode(create_op["imageAsset"]["data"]) == IMAGE_BYTES
        assert uploaded.id == f"customers/{CUSTOMER_ID}/assets/999"
        assert uploaded.extra["asset_id"] == "999"

    def test_upload_image_url_only_rejected(self, adapter, fake_http):
        with pytest.raises(ValidationError, match="inline"):
            adapter.upload_media(AdMediaAsset(media_type=AdMediaType.IMAGE, url="https://example.com/banner.png"))
        assert fake_http.calls == []

    def test_upload_video_unsupported(self, adapter, fake_http):
        with pytest.raises(UnsupportedFeatureError, match="YouTube"):
            adapter.upload_media(AdMediaAsset(media_type=AdMediaType.VIDEO, content=b"video-bytes"))
        assert fake_http.calls == []

    def test_create_creative_unsupported(self, adapter, fake_http):
        creative = AdCreative(title="Headline", body="Description", landing_url="https://example.com")
        with pytest.raises(UnsupportedFeatureError, match="creative resource"):
            adapter.create_creative(creative)
        assert fake_http.calls == []


# ── OAuth ──

OAUTH_CREDENTIALS = {"client_id": "test_client_id", "client_secret": "test_client_secret"}

TOKEN_RESPONSE = {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "expires_in": 3599,
    "token_type": "Bearer",
}


def make_oauth_adapter(token_response: dict | None = None) -> tuple[GoogleAdsAdapter, FakeHttpClient]:
    fake = FakeHttpClient()
    fake.add("POST", "oauth2.googleapis.com/token", token_response or dict(TOKEN_RESPONSE))
    adapter = GoogleAdsAdapter(credentials=dict(OAUTH_CREDENTIALS), http_client=fake)
    return adapter, fake


class TestGoogleAdsOAuth:
    """OAuthCapability: authorization URL, code exchange, token refresh."""

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Google Ads"
        assert len(manifest.auth.oauth.credential_fields) == 2
        assert manifest.auth.oauth.scopes == ["https://www.googleapis.com/auth/adwords"]

    def test_access_token_not_required_in_manifest(self):
        access_token_field = next(f for f in manifest.auth.required_fields if f.name == "access_token")
        assert access_token_field.required is False
        developer_token_field = next(f for f in manifest.auth.required_fields if f.name == "developer_token")
        assert developer_token_field.required is True
        customer_id_field = next(f for f in manifest.auth.required_fields if f.name == "customer_id")
        assert customer_id_field.required is True

    def test_get_authorize_url(self):
        oauth_adapter, _ = make_oauth_adapter()
        url = oauth_adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert "accounts.google.com" in url
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "access_type=offline" in url

    def test_exchange_code_for_token(self):
        oauth_adapter, fake = make_oauth_adapter()
        tokens = oauth_adapter.exchange_code_for_token("auth-code", "https://example.com/callback")

        call = fake.last_call()
        assert call.method == "POST"
        assert "oauth2.googleapis.com/token" in call.path
        assert call.kwargs["data"] == {
            "code": "auth-code",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "https://example.com/callback",
            "grant_type": "authorization_code",
        }
        assert tokens.access_token == "new-access-token"
        assert tokens.refresh_token == "new-refresh-token"
        assert tokens.expires_in == 3599
        assert tokens.extra["credentials"] == {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        }

    def test_refresh_token(self):
        oauth_adapter, fake = make_oauth_adapter(
            {"access_token": "refreshed-access-token", "expires_in": 3599, "token_type": "Bearer"}
        )
        tokens = oauth_adapter.refresh_token("old-refresh-token")

        call = fake.last_call()
        assert call.method == "POST"
        assert call.kwargs["data"] == {
            "refresh_token": "old-refresh-token",
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "grant_type": "refresh_token",
        }
        assert tokens.access_token == "refreshed-access-token"
        assert tokens.refresh_token == "old-refresh-token"
        assert tokens.extra["credentials"]["access_token"] == "refreshed-access-token"
        assert tokens.extra["credentials"]["refresh_token"] == "old-refresh-token"

    def test_adapter_constructible_with_only_client_credentials(self):
        oauth_adapter, _ = make_oauth_adapter()
        assert oauth_adapter._client_id == "test_client_id"
        assert oauth_adapter._client_secret == "test_client_secret"
        assert oauth_adapter.validate_credentials() is True

    def test_full_credentials_still_validate(self, adapter):
        assert adapter.validate_credentials() is True

    def test_supports_oauth_capability(self, adapter):
        assert adapter.supports(OAuthCapability) is True


ACCESSIBLE_CUSTOMERS = {"resourceNames": [f"customers/{CUSTOMER_ID}", "customers/2222222222"]}


class TestListAccessibleCustomers:
    """Connect-flow helper: customers:listAccessibleCustomers with an optional token override."""

    def test_returns_picker_rows_with_stored_token(self, adapter, fake_http):
        fake_http.add("GET", "customers:listAccessibleCustomers", ACCESSIBLE_CUSTOMERS)
        customers = adapter.list_accessible_customers()
        assert customers == [{"customer_id": CUSTOMER_ID}, {"customer_id": "2222222222"}]
        call = fake_http.last_call()
        assert call.method == "GET"
        assert call.path == "customers:listAccessibleCustomers"
        assert call.kwargs["headers"]["Authorization"] == "Bearer access-token"
        assert call.kwargs["headers"]["developer-token"] == "dev-token"

    def test_no_login_customer_id_header_even_when_configured(self, adapter, fake_http):
        # The adapter fixture sets login_customer_id — this endpoint must not send it.
        fake_http.add("GET", "customers:listAccessibleCustomers", ACCESSIBLE_CUSTOMERS)
        adapter.list_accessible_customers()
        assert "login-customer-id" not in fake_http.last_call().kwargs["headers"]

    def test_explicit_token_overrides_credential(self, adapter, fake_http):
        fake_http.add("GET", "customers:listAccessibleCustomers", ACCESSIBLE_CUSTOMERS)
        adapter.list_accessible_customers(access_token="FRESH_TOKEN")
        headers = fake_http.last_call().kwargs["headers"]
        assert headers["Authorization"] == "Bearer FRESH_TOKEN"
        assert headers["developer-token"] == "dev-token"

    def test_empty_resource_names_returns_empty_list(self, adapter, fake_http):
        fake_http.add("GET", "customers:listAccessibleCustomers", {})
        assert adapter.list_accessible_customers() == []
