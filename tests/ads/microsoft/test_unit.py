"""
Microsoft Ads (Bing Ads) adapter unit tests + contract tests.

The Bing Ads API v13 is SOAP and every Campaign Management call POSTs to the
same service URL, so the canned responses are callables that dispatch on the
request envelope contents (the ``*Request`` element name and its ids) instead
of on the URL path. Reporting calls go to the separate reporting service URL
and download from a third fake host that serves an in-memory ZIP'd CSV.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

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
)
from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)
from bapp_connectors.providers.ads.microsoft.adapter import MicrosoftAdsAdapter
from bapp_connectors.providers.ads.microsoft.errors import classify_soap_fault
from bapp_connectors.providers.ads.microsoft.manifest import manifest
from bapp_connectors.providers.ads.microsoft.mappers import (
    ad_from_ms,
    ad_to_ms,
    campaign_from_ms,
    date_from_ms,
    date_to_ms,
    objective_from_campaign_type,
    objective_to_campaign_type,
    status_from_ms,
    status_to_ms,
)
from tests.ads.contract import AdsContractTests
from tests.fake_http import FakeHttpClient

CUSTOMER_ID = "9990001"
ACCOUNT_ID = "5550001"

CREDENTIALS = {
    "developer_token": "dev-token",
    "access_token": "access-token",
    "customer_id": CUSTOMER_ID,
    "account_id": ACCOUNT_ID,
}

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
CM_NS = "https://bingads.microsoft.com/CampaignManagement/v13"
REPORTING_NS = "https://bingads.microsoft.com/Reporting/v13"
ARRAYS_NS = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

DOWNLOAD_URL = "https://reportdownload.example.test/report.zip"

METRIC_COLUMNS = ["Impressions", "Clicks", "Spend", "Ctr", "AverageCpc", "Conversions", "Revenue"]
METRIC_VALUES = ["1000", "50", "12.5", "5.00%", "0.25", "3", "150"]


@dataclass
class FakeResponse:
    """Minimal stand-in for requests.Response as consumed by the SOAP client."""

    text: str = ""
    content: bytes = b""
    status_code: int = 200

    @property
    def ok(self) -> bool:
        return self.status_code < 400


def _soap(inner: str) -> str:
    return f'<s:Envelope xmlns:s="{SOAP_NS}"><s:Body>{inner}</s:Body></s:Envelope>'


def _ok(inner: str) -> FakeResponse:
    return FakeResponse(text=_soap(inner))


# ── Canned Campaign Management responses ──


def _campaign_xml(cid: str, name: str, status: str = "Active", ctype: str = "Search", budget: str = "25") -> str:
    return (
        f"<Campaign><BudgetType>DailyBudgetStandard</BudgetType><CampaignType>{ctype}</CampaignType>"
        f"<DailyBudget>{budget}</DailyBudget><Id>{cid}</Id><Name>{name}</Name>"
        f"<Status>{status}</Status><TimeZone>BucharestIstanbulMinskNicosia</TimeZone></Campaign>"
    )


def _ad_group_xml(gid: str, name: str, status: str = "Active") -> str:
    return (
        f"<AdGroup><CpcBid><Amount>0.5</Amount></CpcBid>"
        f"<EndDate><Day>31</Day><Month>12</Month><Year>2026</Year></EndDate>"
        f"<Id>{gid}</Id><Name>{name}</Name>"
        f"<StartDate><Day>1</Day><Month>6</Month><Year>2026</Year></StartDate>"
        f"<Status>{status}</Status></AdGroup>"
    )


def _ad_xml(ad_id: str, status: str = "Active") -> str:
    return (
        f'<Ad i:type="ResponsiveSearchAd" xmlns:i="{XSI_NS}">'
        f'<FinalUrls xmlns:a="{ARRAYS_NS}"><a:string>https://example.com</a:string></FinalUrls>'
        f"<Id>{ad_id}</Id><Status>{status}</Status><Type>ResponsiveSearch</Type>"
        f'<Descriptions><AssetLink><Asset i:type="TextAsset"><Text>Description</Text></Asset></AssetLink></Descriptions>'
        f'<Headlines><AssetLink><Asset i:type="TextAsset"><Text>Headline</Text></Asset></AssetLink></Headlines>'
        f"</Ad>"
    )


CAMPAIGNS_XML = (
    _campaign_xml("111", "Search campaign")
    + _campaign_xml("222", "Shopping campaign", status="Paused", ctype="Shopping", budget="40")
    + _campaign_xml("999", "New campaign", status="Paused", budget="10")
)

AD_GROUPS_XML = _ad_group_xml("333", "Ad group one") + _ad_group_xml("444", "New ad group", status="Paused")

ADS_XML = _ad_xml("555") + _ad_xml("888", status="Paused")


def _ids_response(response_name: str, container: str, ids: list[str]) -> FakeResponse:
    longs = "".join(f"<a:long>{i}</a:long>" for i in ids)
    return _ok(
        f'<{response_name} xmlns="{CM_NS}">'
        f'<{container} xmlns:a="{ARRAYS_NS}">{longs}</{container}>'
        f"<PartialErrors/></{response_name}>"
    )


def _cm_dispatch(method: str, path: str, kwargs: dict) -> FakeResponse:
    """Dispatch a Campaign Management SOAP request on its body contents."""
    body = kwargs["data"].decode("utf-8")
    if "GetCampaignsByAccountIdRequest" in body:
        return _ok(
            f'<GetCampaignsByAccountIdResponse xmlns="{CM_NS}">'
            f"<Campaigns>{CAMPAIGNS_XML}</Campaigns></GetCampaignsByAccountIdResponse>"
        )
    if "AddCampaignsRequest" in body:
        return _ids_response("AddCampaignsResponse", "CampaignIds", ["999"])
    if "UpdateCampaignsRequest" in body:
        return _ok(f'<UpdateCampaignsResponse xmlns="{CM_NS}"><PartialErrors/></UpdateCampaignsResponse>')
    if "GetAdGroupsByCampaignIdRequest" in body:
        match = re.search(r"<CampaignId>(\d+)</CampaignId>", body)
        groups = AD_GROUPS_XML if match and match.group(1) == "111" else ""
        return _ok(
            f'<GetAdGroupsByCampaignIdResponse xmlns="{CM_NS}">'
            f"<AdGroups>{groups}</AdGroups></GetAdGroupsByCampaignIdResponse>"
        )
    if "AddAdGroupsRequest" in body:
        return _ids_response("AddAdGroupsResponse", "AdGroupIds", ["444"])
    if "UpdateAdGroupsRequest" in body:
        return _ok(f'<UpdateAdGroupsResponse xmlns="{CM_NS}"><PartialErrors/></UpdateAdGroupsResponse>')
    if "GetAdsByAdGroupIdRequest" in body:
        match = re.search(r"<AdGroupId>(\d+)</AdGroupId>", body)
        ads = ADS_XML if match and match.group(1) == "333" else ""
        return _ok(f'<GetAdsByAdGroupIdResponse xmlns="{CM_NS}"><Ads>{ads}</Ads></GetAdsByAdGroupIdResponse>')
    if "AddAdsRequest" in body:
        return _ids_response("AddAdsResponse", "AdIds", ["888"])
    if "UpdateAdsRequest" in body:
        return _ok(f'<UpdateAdsResponse xmlns="{CM_NS}"><PartialErrors/></UpdateAdsResponse>')
    raise AssertionError(f"Unexpected Campaign Management SOAP request: {body[:200]}")


# ── Canned Reporting responses ──


def _report_zip(submitted_body: str) -> bytes:
    """Build an in-memory ZIP'd CSV matching the report type that was submitted."""
    if "AdPerformanceReportRequest" in submitted_body:
        id_column, id_values = "AdId", ["555", "888"]
    elif "AdGroupPerformanceReportRequest" in submitted_body:
        id_column, id_values = "AdGroupId", ["333"]
    elif "CampaignPerformanceReportRequest" in submitted_body:
        id_column, id_values = "CampaignId", ["111"]
    else:
        id_column, id_values = "", [""]

    header = ",".join(([id_column] if id_column else []) + METRIC_COLUMNS)
    data_lines = [",".join(([value] if id_column else []) + METRIC_VALUES) for value in id_values]
    csv_text = "\n".join(
        [
            '"Report Name: bapp-connectors insights"',
            '"Report Time: 6/1/2026 - 6/30/2026"',
            "",
            header,
            *data_lines,
            "",
            "©2026 Microsoft Corporation. All rights reserved.",
        ]
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("report.csv", csv_text)
    return buffer.getvalue()


# ── Fixtures ──


@pytest.fixture
def fake_http() -> FakeHttpClient:
    fake = FakeHttpClient(base_url=manifest.base_url)
    state: dict = {}

    def reporting_dispatch(method: str, path: str, kwargs: dict) -> FakeResponse:
        body = kwargs["data"].decode("utf-8")
        if "SubmitGenerateReportRequest" in body:
            state["report_body"] = body
            return _ok(
                f'<SubmitGenerateReportResponse xmlns="{REPORTING_NS}">'
                f"<ReportRequestId>report-123</ReportRequestId></SubmitGenerateReportResponse>"
            )
        if "PollGenerateReportRequest" in body:
            return _ok(
                f'<PollGenerateReportResponse xmlns="{REPORTING_NS}"><ReportRequestStatus>'
                f"<ReportDownloadUrl>{DOWNLOAD_URL}</ReportDownloadUrl><Status>Success</Status>"
                f"</ReportRequestStatus></PollGenerateReportResponse>"
            )
        raise AssertionError(f"Unexpected Reporting SOAP request: {body[:200]}")

    def download(method: str, path: str, kwargs: dict) -> FakeResponse:
        return FakeResponse(content=_report_zip(state.get("report_body", "")))

    # Order matters: the campaign-management rule matches any POST path (all
    # SOAP calls share one URL), so the more specific rules go first.
    fake.add("POST", "reporting.api.bingads", reporting_dispatch)
    fake.add("GET", "reportdownload.example.test", download)
    fake.add("POST", "", _cm_dispatch)
    return fake


@pytest.fixture
def adapter(fake_http) -> MicrosoftAdsAdapter:
    return MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


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
    return AdGroup(
        campaign_id="111",
        name="New ad group",
        bid_amount=Decimal("0.5"),
        start_time=datetime(2026, 6, 1),
        end_time=datetime(2026, 12, 31),
    )


@pytest.fixture
def ad_draft() -> Ad:
    return Ad(
        ad_group_id="333",
        name="New ad",
        creative=AdCreative(title="Headline", body="Description", landing_url="https://example.com"),
    )


def _request_body(fake: FakeHttpClient, marker: str) -> str:
    """Return the decoded SOAP envelope of the first recorded call containing ``marker``."""
    for call in fake.calls:
        data = call.kwargs.get("data")
        if isinstance(data, bytes) and marker in data.decode("utf-8"):
            return data.decode("utf-8")
    raise AssertionError(f"No recorded SOAP request contains '{marker}'")


class TestMicrosoftAdsContract(AdsContractTests):
    """Run all ads contract tests for Microsoft Ads."""

    @pytest.fixture
    def adapter(self, fake_http) -> MicrosoftAdsAdapter:
        return MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake_http)


class TestMicrosoftAdsMappers:
    """Microsoft-specific mapper tests: status/objective maps, dates, creatives."""

    def test_status_read_map(self):
        assert status_from_ms("Active") is AdEntityStatus.ACTIVE
        assert status_from_ms("Paused") is AdEntityStatus.PAUSED
        assert status_from_ms("Deleted") is AdEntityStatus.DELETED
        assert status_from_ms("Suspended") is AdEntityStatus.PAUSED
        assert status_from_ms("BudgetPaused") is AdEntityStatus.PAUSED
        assert status_from_ms("Expired") is AdEntityStatus.ENDED
        assert status_from_ms("SomethingNew") is AdEntityStatus.UNKNOWN

    def test_status_write_map(self):
        assert status_to_ms(AdEntityStatus.ACTIVE) == "Active"
        assert status_to_ms(AdEntityStatus.PAUSED) == "Paused"
        assert status_to_ms(AdEntityStatus.DELETED) == "Deleted"
        with pytest.raises(ValidationError):
            status_to_ms(AdEntityStatus.ARCHIVED)

    def test_objective_read_map(self):
        assert objective_from_campaign_type("Search") is AdObjective.TRAFFIC
        assert objective_from_campaign_type("Shopping") is AdObjective.SALES
        assert objective_from_campaign_type("Audience") is AdObjective.AWARENESS
        assert objective_from_campaign_type("PerformanceMax") is AdObjective.SALES
        assert objective_from_campaign_type("DynamicSearchAds") is AdObjective.OTHER

    def test_objective_write_map_defaults_to_search(self):
        assert objective_to_campaign_type(AdObjective.TRAFFIC) == "Search"
        assert objective_to_campaign_type(AdObjective.SALES) == "Shopping"
        assert objective_to_campaign_type(AdObjective.AWARENESS) == "Audience"
        assert objective_to_campaign_type(AdObjective.LEADS) == "Search"
        assert objective_to_campaign_type(None) == "Search"

    def test_date_round_trip(self):
        moment = datetime(2026, 6, 1)
        as_ms = date_to_ms(moment)
        assert as_ms == {"Day": "1", "Month": "6", "Year": "2026"}
        assert date_from_ms(as_ms) == moment
        assert date_from_ms(None) is None
        assert date_from_ms({"Day": "x"}) is None

    def test_campaign_from_ms(self):
        campaign = campaign_from_ms(
            {
                "Id": "111",
                "Name": "Search campaign",
                "Status": "Active",
                "BudgetType": "DailyBudgetStandard",
                "DailyBudget": "25",
                "TimeZone": "BucharestIstanbulMinskNicosia",
                "CampaignType": "Search",
            }
        )
        assert campaign.id == "111"
        assert campaign.status is AdEntityStatus.ACTIVE
        assert campaign.objective is AdObjective.TRAFFIC
        assert campaign.daily_budget == Decimal("25")
        assert campaign.extra["campaign_type"] == "Search"
        assert campaign.extra["time_zone"] == "BucharestIstanbulMinskNicosia"

    def test_ad_to_ms_requires_full_creative(self):
        with pytest.raises(ValidationError):
            ad_to_ms(Ad(ad_group_id="333", name="No creative"))
        with pytest.raises(ValidationError):
            ad_to_ms(Ad(ad_group_id="333", name="Partial", creative=AdCreative(title="Only title")))

    def test_ad_from_ms_legacy_text_ad(self):
        ad = ad_from_ms(
            {
                "Id": "42",
                "Type": "Text",
                "Status": "Active",
                "Title": "Old title",
                "Text": "Old body",
                "FinalUrls": ["https://example.com/legacy"],
            },
            ad_group_id="333",
        )
        assert ad.creative.title == "Old title"
        assert ad.creative.body == "Old body"
        assert ad.creative.landing_url == "https://example.com/legacy"


AUTH_FAULT = _soap(
    "<s:Fault><faultcode>s:Server</faultcode><faultstring>Invalid client data.</faultstring>"
    "<detail><AdApiFaultDetail><Errors><AdApiError><Code>105</Code>"
    "<Message>Authentication failed. Either supplied credentials are invalid or the account is inactive.</Message>"
    "</AdApiError></Errors></AdApiFaultDetail></detail></s:Fault>"
)

THROTTLE_FAULT = _soap(
    "<s:Fault><faultstring>Server error.</faultstring><detail><ApiFaultDetail><OperationErrors>"
    "<OperationError><Code>117</Code><Message>You have exceeded the call rate limit.</Message></OperationError>"
    "</OperationErrors></ApiFaultDetail></detail></s:Fault>"
)


class TestMicrosoftAdsErrors:
    """SOAP fault classification: auth codes, throttling, generic 4xx/5xx."""

    def test_auth_code_105(self):
        with pytest.raises(AuthenticationError):
            classify_soap_fault(AUTH_FAULT, 500)

    def test_auth_token_string(self):
        with pytest.raises(AuthenticationError):
            classify_soap_fault("<Fault><faultstring>AuthenticationTokenExpired</faultstring></Fault>", 500)

    def test_invalid_credentials_string(self):
        with pytest.raises(AuthenticationError):
            classify_soap_fault("<Error>InvalidCredentials</Error>", None)

    def test_throttle_code_117(self):
        with pytest.raises(RateLimitError):
            classify_soap_fault(THROTTLE_FAULT, 500)

    def test_throttle_string(self):
        with pytest.raises(RateLimitError):
            classify_soap_fault("<Fault><faultstring>Request throttled, slow down</faultstring></Fault>", 500)

    def test_generic_4xx_is_permanent(self):
        with pytest.raises(PermanentProviderError):
            classify_soap_fault("<Fault><faultstring>Bad entity</faultstring></Fault>", 400)

    def test_generic_5xx_is_retryable_provider_error(self):
        with pytest.raises(ProviderError):
            classify_soap_fault("<Fault><faultstring>Boom</faultstring></Fault>", 500)

    def test_soap_fault_response_maps_to_authentication_error(self):
        fake = FakeHttpClient()
        fake.add("POST", "", lambda method, path, kwargs: FakeResponse(text=AUTH_FAULT, status_code=500))
        adapter = MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake)
        with pytest.raises(AuthenticationError):
            adapter.list_campaigns()


class TestMicrosoftAdsClient:
    """SOAP envelope shape: auth header elements, SOAPAction, entity XML."""

    def test_soap_header_contains_all_auth_elements(self, adapter, fake_http):
        adapter.list_campaigns()
        call = fake_http.last_call()
        envelope = call.kwargs["data"].decode("utf-8")
        assert "<AuthenticationToken>access-token</AuthenticationToken>" in envelope
        assert "<DeveloperToken>dev-token</DeveloperToken>" in envelope
        assert f"<CustomerId>{CUSTOMER_ID}</CustomerId>" in envelope
        assert f"<CustomerAccountId>{ACCOUNT_ID}</CustomerAccountId>" in envelope
        headers = call.kwargs["headers"]
        assert headers["SOAPAction"] == "GetCampaignsByAccountId"
        assert headers["Content-Type"].startswith("text/xml")

    def test_create_ad_builds_responsive_search_ad_xml(self, adapter, fake_http, ad_draft):
        created = adapter.create_ad(ad_draft)
        assert created.id == "888"
        body = _request_body(fake_http, "AddAdsRequest")
        assert "<AdGroupId>333</AdGroupId>" in body
        assert 'i:type="ResponsiveSearchAd"' in body
        assert 'i:type="TextAsset"' in body
        assert "<Text>Headline</Text>" in body
        assert "<Text>Description</Text>" in body
        assert "<a:string>https://example.com</a:string>" in body
        # SOAP is order-sensitive: Descriptions < FinalUrls < Headlines < Status.
        assert body.index("<Descriptions>") < body.index("<FinalUrls") < body.index("<Headlines>")
        assert body.index("<Headlines>") < body.index("<Status>")

    def test_create_ad_group_emits_date_and_bid_elements(self, adapter, fake_http, ad_group_draft):
        created = adapter.create_ad_group(ad_group_draft)
        assert created.id == "444"
        body = _request_body(fake_http, "AddAdGroupsRequest")
        assert "<CampaignId>111</CampaignId>" in body
        assert "<CpcBid><Amount>0.5</Amount></CpcBid>" in body
        assert "<StartDate><Day>1</Day><Month>6</Month><Year>2026</Year></StartDate>" in body
        assert "<EndDate><Day>31</Day><Month>12</Month><Year>2026</Year></EndDate>" in body

    def test_ad_group_dates_parsed_from_response(self, adapter):
        ad_group = adapter.get_ad_group("333")
        assert ad_group.campaign_id == "111"
        assert ad_group.bid_amount == Decimal("0.5")
        assert ad_group.start_time == datetime(2026, 6, 1)
        assert ad_group.end_time == datetime(2026, 12, 31)

    def test_special_characters_escaped_in_request(self, adapter, fake_http):
        adapter.create_campaign(AdCampaign(name="Cats & <Dogs>", daily_budget=Decimal("10")))
        body = _request_body(fake_http, "AddCampaignsRequest")
        assert "<Name>Cats &amp; &lt;Dogs&gt;</Name>" in body


class TestMicrosoftAdsAdapter:
    """Adapter behaviour: parent-scoped listings, id resolution, update shapes."""

    def test_list_ad_groups_requires_campaign_id(self, adapter):
        with pytest.raises(ValidationError, match="campaign_id"):
            adapter.list_ad_groups()

    def test_list_ads_requires_ad_group_id(self, adapter):
        with pytest.raises(ValidationError, match="ad_group_id"):
            adapter.list_ads()

    def test_get_campaign_not_found(self, adapter):
        with pytest.raises(PermanentProviderError):
            adapter.get_campaign("40404")

    def test_create_campaign_request_shape(self, adapter, fake_http, campaign_draft):
        created = adapter.create_campaign(campaign_draft)
        assert created.id == "999"
        body = _request_body(fake_http, "AddCampaignsRequest")
        assert f"<AccountId>{ACCOUNT_ID}</AccountId>" in body
        assert "<BudgetType>DailyBudgetStandard</BudgetType>" in body
        assert "<CampaignType>Search</CampaignType>" in body
        assert "<DailyBudget>10</DailyBudget>" in body
        assert "<Status>Paused</Status>" in body  # unset draft status defaults to Paused

    def test_update_campaign_fields(self, adapter, fake_http):
        campaign = adapter.update_campaign("111", {"name": "Renamed", "daily_budget": Decimal("5")})
        assert campaign.id == "111"
        body = _request_body(fake_http, "UpdateCampaignsRequest")
        assert "<Id>111</Id>" in body
        assert "<Name>Renamed</Name>" in body
        assert "<DailyBudget>5</DailyBudget>" in body

    def test_update_campaign_unsupported_field_rejected(self, adapter):
        with pytest.raises(ValidationError, match="objective"):
            adapter.update_campaign("111", {"objective": AdObjective.SALES})

    def test_set_campaign_status_deleted_via_update(self, adapter, fake_http):
        adapter.set_campaign_status("111", AdEntityStatus.DELETED)
        body = _request_body(fake_http, "UpdateCampaignsRequest")
        assert "<Status>Deleted</Status>" in body

    def test_set_ad_status_resolves_ad_group_via_scan(self, adapter, fake_http):
        ad = adapter.set_ad_status("555", AdEntityStatus.PAUSED)
        assert isinstance(ad, Ad)
        body = _request_body(fake_http, "UpdateAdsRequest")
        assert "<AdGroupId>333</AdGroupId>" in body
        assert "<Id>555</Id>" in body
        assert "<Status>Paused</Status>" in body

    def test_set_ad_status_uses_cache_after_listing(self, adapter, fake_http):
        adapter.list_ads(ad_group_id="333")
        calls_before = len(fake_http.calls)
        adapter.set_ad_status("555", AdEntityStatus.PAUSED)
        bodies = [c.kwargs["data"].decode("utf-8") for c in fake_http.calls[calls_before:]]
        # Cache hit: no GetCampaignsByAccountId scan needed to find the ad group.
        assert not any("GetCampaignsByAccountIdRequest" in b for b in bodies)

    def test_update_ad_non_status_change_raises(self, adapter):
        with pytest.raises(ValidationError, match="status"):
            adapter.update_ad("555", {"name": "New name"})

    def test_ad_creative_mapped_from_assets(self, adapter):
        ad = adapter.get_ad("555")
        assert ad.creative.title == "Headline"
        assert ad.creative.body == "Description"
        assert ad.creative.landing_url == "https://example.com"
        assert ad.extra["ad_type"] == "ResponsiveSearch"

    def test_test_connection_mentions_account(self, adapter):
        result = adapter.test_connection()
        assert result.success is True
        assert ACCOUNT_ID in result.message

    def test_test_connection_failure(self):
        fake = FakeHttpClient()
        fake.add("POST", "", lambda method, path, kwargs: FakeResponse(text=AUTH_FAULT, status_code=500))
        adapter = MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake)
        result = adapter.test_connection()
        assert result.success is False


class TestMicrosoftAdsInsights:
    """Reporting service flow: submit/poll/download and CSV parsing."""

    def test_campaign_insights_request_and_csv_parsing(self, adapter, fake_http):
        insights = adapter.get_insights(
            AdInsightsLevel.CAMPAIGN,
            entity_id="111",
            since=datetime(2026, 6, 1),
            until=datetime(2026, 6, 30),
        )
        submit_body = _request_body(fake_http, "SubmitGenerateReportRequest")
        assert 'i:type="CampaignPerformanceReportRequest"' in submit_body
        assert "<Aggregation>Summary</Aggregation>" in submit_body
        assert "<Format>Csv</Format>" in submit_body
        assert f"<a:long>{ACCOUNT_ID}</a:long>" in submit_body
        assert "<CampaignReportScope>" in submit_body
        assert "<CampaignId>111</CampaignId>" in submit_body
        assert (
            "<CustomDateRangeStart><Day>1</Day><Month>6</Month><Year>2026</Year></CustomDateRangeStart>" in submit_body
        )
        assert "<CustomDateRangeEnd><Day>30</Day><Month>6</Month><Year>2026</Year></CustomDateRangeEnd>" in submit_body

        assert len(insights) == 1
        row = insights[0]
        assert row.level is AdInsightsLevel.CAMPAIGN
        assert row.entity_id == "111"
        assert row.impressions == 1000
        assert row.clicks == 50
        assert row.spend == Decimal("12.5")
        assert row.ctr == 5.0  # "5.00%" with the percent sign stripped
        assert row.cpc == Decimal("0.25")
        assert row.conversions == 3.0
        assert row.conversion_value == Decimal("150")
        assert row.currency == "USD"  # from the currency setting default
        assert row.date_start == datetime(2026, 6, 1)
        assert row.date_stop == datetime(2026, 6, 30)

    def test_account_insights_use_predefined_time(self, adapter, fake_http):
        insights = adapter.get_insights(AdInsightsLevel.ACCOUNT)
        submit_body = _request_body(fake_http, "SubmitGenerateReportRequest")
        assert 'i:type="AccountPerformanceReportRequest"' in submit_body
        assert "<PredefinedTime>LastSevenDays</PredefinedTime>" in submit_body
        assert len(insights) == 1
        assert insights[0].entity_id == ACCOUNT_ID
        assert insights[0].spend == Decimal("12.5")

    def test_ad_group_insights_scope_includes_campaign(self, adapter, fake_http):
        insights = adapter.get_insights(AdInsightsLevel.AD_GROUP, entity_id="333")
        submit_body = _request_body(fake_http, "SubmitGenerateReportRequest")
        assert "<AdGroupReportScope>" in submit_body
        assert "<AdGroupId>333</AdGroupId>" in submit_body
        assert "<CampaignId>111</CampaignId>" in submit_body  # resolved via the hierarchy scan
        assert insights[0].entity_id == "333"

    def test_ad_insights_filtered_client_side(self, adapter):
        all_rows = adapter.get_insights(AdInsightsLevel.AD)
        assert {row.entity_id for row in all_rows} == {"555", "888"}
        filtered = adapter.get_insights(AdInsightsLevel.AD, entity_id="555")
        assert [row.entity_id for row in filtered] == ["555"]

    def test_currency_setting_labels_spend(self, fake_http):
        adapter = MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake_http, config={"currency": "RON"})
        insights = adapter.get_insights(AdInsightsLevel.CAMPAIGN, entity_id="111")
        assert insights[0].currency == "RON"

    def test_report_error_status_raises(self, fake_http):
        def failing_reporting(method: str, path: str, kwargs: dict) -> FakeResponse:
            body = kwargs["data"].decode("utf-8")
            if "SubmitGenerateReportRequest" in body:
                return _ok(
                    f'<SubmitGenerateReportResponse xmlns="{REPORTING_NS}">'
                    f"<ReportRequestId>report-err</ReportRequestId></SubmitGenerateReportResponse>"
                )
            return _ok(
                f'<PollGenerateReportResponse xmlns="{REPORTING_NS}"><ReportRequestStatus>'
                f"<Status>Error</Status></ReportRequestStatus></PollGenerateReportResponse>"
            )

        fake = FakeHttpClient()
        fake.add("POST", "reporting.api.bingads", failing_reporting)
        adapter = MicrosoftAdsAdapter(credentials=dict(CREDENTIALS), http_client=fake)
        with pytest.raises(ProviderError, match="report"):
            adapter.get_insights(AdInsightsLevel.ACCOUNT)


# ── OAuth ──

OAUTH_CREDENTIALS = {"client_id": "test_client_id", "client_secret": "test_client_secret"}

TOKEN_RESPONSE = {
    "access_token": "new-access-token",
    "refresh_token": "new-refresh-token",
    "expires_in": 3599,
    "token_type": "Bearer",
}


def make_oauth_adapter(token_response: dict | None = None) -> tuple[MicrosoftAdsAdapter, FakeHttpClient]:
    fake = FakeHttpClient()
    fake.add("POST", "login.microsoftonline.com", token_response or dict(TOKEN_RESPONSE))
    adapter = MicrosoftAdsAdapter(credentials=dict(OAUTH_CREDENTIALS), http_client=fake)
    return adapter, fake


class TestMicrosoftAdsOAuth:
    """OAuthCapability: Microsoft identity platform authorize/exchange/refresh."""

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with Microsoft Ads"
        assert len(manifest.auth.oauth.credential_fields) == 2
        assert manifest.auth.oauth.scopes == ["https://ads.microsoft.com/msads.manage", "offline_access"]

    def test_credential_field_requirements(self):
        fields = {f.name: f for f in manifest.auth.required_fields}
        assert fields["access_token"].required is False
        assert fields["developer_token"].required is True
        assert fields["customer_id"].required is True
        assert fields["account_id"].required is True
        assert fields["developer_token"].sensitive is True
        assert fields["access_token"].sensitive is True

    def test_get_authorize_url(self):
        oauth_adapter, _ = make_oauth_adapter()
        url = oauth_adapter.get_authorize_url("https://example.com/callback", state="abc123")
        assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
        assert "client_id=test_client_id" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url
        assert "state=abc123" in url
        assert "msads.manage" in url
        assert "offline_access" in url

    def test_exchange_code_for_token(self):
        oauth_adapter, fake = make_oauth_adapter()
        tokens = oauth_adapter.exchange_code_for_token("auth-code", "https://example.com/callback")

        call = fake.last_call()
        assert call.method == "POST"
        assert "login.microsoftonline.com/common/oauth2/v2.0/token" in call.path
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
        assert oauth_adapter.validate_credentials() is True

    def test_supports_oauth_capability(self, adapter):
        assert adapter.supports(OAuthCapability) is True
