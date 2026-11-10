"""Guard on the ``@ai_method`` markers of the ads provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's ad
platform credentials. Every one of them was read down to its HTTP request; the lists below are
that review. Creates, updates, status changes and uploads are ``write`` (or unmarked).

Generic methods that take an arbitrary path, resource, field list or raw query are never ``read``:
on the Graph API ``fields=access_token`` on a Page returns its Page token, a GAQL query can reach a
lead-form webhook secret, a Bing poll returns a pre-signed download URL. The agent gets narrow
wrappers instead (fixed edges and fields; a GAQL SELECT checked against a resource allow-list;
analytics with a fixed metric list). No read takes a host or API version.
"""

from __future__ import annotations

import inspect
import json
from datetime import date
from unittest.mock import MagicMock

import pytest

from bapp_connectors.core.ai import ai_methods
from bapp_connectors.core.errors import ValidationError
from tests.core import ai_guard

FAMILY = "ads"
ADS_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "facebook": {
        "get_ad_account_info",  # GET act_{id}, fixed fields
        "get_ad_info",  # GET {id}, fixed ad fields
        "get_ad_set_info",
        "get_campaign_info",
        "get_insights_report",  # GET {id|act_id}/insights, fixed fields; level/date_preset are Literals
        "list_account_ad_sets",  # GET act_{id}/adsets, fixed fields
        "list_account_ads",
        "list_account_campaigns",
        "list_account_creatives",
        "list_account_custom_audiences",
    },
    "google": {
        "run_report",  # POST googleAds:search (read-only GAQL), SELECT + FROM allow-list checked
    },
    "linkedin": {
        "get_account",
        "get_analytics_report",  # GET adAnalytics, fixed fields, account pinned, URNs encoded
        "get_campaign",
        "get_campaign_group",
        "get_creative",
        "list_campaign_groups",
        "list_campaigns",
        "list_creatives",
    },
    "microsoft": {
        "get_ad_groups",  # SOAP GetAdGroupsByCampaignId (POST, nothing created)
        "get_ads",
        "get_campaigns",
    },
    "pinterest": {
        "get_account_analytics",  # GET .../analytics, params keys allow-listed
        "get_ad",
        "get_ad_account",
        "get_ad_group",
        "get_ad_group_analytics",
        "get_ad_analytics",
        "get_campaign",
        "get_campaign_analytics",
        "list_ad_groups",
        "list_ads",
        "list_campaigns",
    },
    "tiktok": {
        "get_adgroups",
        "get_ads",
        "get_campaigns",
        "get_report",  # GET report/integrated/get/, params keys allow-listed (no advertiser_id)
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

# Opaque pagination cursors and the GAQL text: they only reach a query string or a JSON body.
REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = {
    ("facebook", "get_insights_report", "after"),
    ("facebook", "list_account_ad_sets", "after"),
    ("facebook", "list_account_ads", "after"),
    ("facebook", "list_account_campaigns", "after"),
    ("facebook", "list_account_creatives", "after"),
    ("facebook", "list_account_custom_audiences", "after"),
    ("google", "run_report", "query"),
    ("google", "run_report", "page_token"),
    ("linkedin", "list_campaign_groups", "page_token"),
    ("linkedin", "list_campaigns", "page_token"),
    ("linkedin", "list_creatives", "page_token"),
    ("pinterest", "list_campaigns", "bookmark"),
    ("pinterest", "list_ad_groups", "bookmark"),
    ("pinterest", "list_ads", "bookmark"),
}

# Public client methods deliberately left without any mark (never offered to an agent).
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("facebook", "account_path"): "path helper",
    ("facebook", "list_edge"): "any Graph path and any fields (me/accounts?fields=access_token)",
    ("facebook", "get_object"): "any object and any fields (a Page's access_token)",
    ("facebook", "get_insights"): "raw params dict (fields, breakdowns) forwarded as-is",
    ("facebook", "create"): "POST to any Graph path",
    ("facebook", "update"): "POST to any Graph object",
    ("facebook", "upload_image"): "multipart upload",
    ("facebook", "upload_video"): "multipart upload / Meta fetches an agent URL",
    ("google", "search"): "raw GAQL over any resource; the agent uses run_report",
    ("google", "mutate"): "mutate on any resource name",
    ("linkedin", "search_ad_accounts"): "takes an access_token override (connect flow)",
    ("linkedin", "analytics"): "params joined verbatim into the query string",
    ("microsoft", "submit_report"): "raw report-request XML",
    ("microsoft", "poll_report"): "returns a pre-signed report download URL",
    ("microsoft", "download_report"): "downloads a URL, returns bytes",
    ("pinterest", "account_path"): "path helper",
    ("tiktok", "upload_image"): "multipart upload / TikTok fetches an agent URL",
    ("tiktok", "upload_video"): "multipart upload / TikTok fetches an agent URL",
}

NOT_MARKED: dict[str, str] = {}


def test_every_ads_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in ADS_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_ads_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    assert public - marked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_a_host_version_or_path(provider):
    """Host, API version and raw paths/fields come from the client, never from the agent."""
    blocked = {"url", "host", "base_url", "version", "api_version", "path", "fields", "access_token", "token"}
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        assert not set(inspect.signature(fn).parameters) & blocked, name


@pytest.mark.parametrize("provider", ["pinterest", "tiktok"])
def test_dict_params_refuse_account_and_auth_keys(provider):
    from bapp_connectors.core.ai import key_allowed

    for name, _fn, info in ai_guard.read_methods(FAMILY, provider):
        for patterns in info.allowed_keys.values():
            for key in ("advertiser_id", "ad_account_id", "access_token", "fields"):
                assert not key_allowed(key, patterns), (name, key)


# ── Facebook: fixed edges and fields, pinned to the connected ad account ──


def _meta_client(response=None):
    from bapp_connectors.providers.ads.facebook.client import MetaAdsClient

    http = MagicMock()
    http.call.return_value = response if response is not None else {"data": []}
    return MetaAdsClient(http, ad_account_id="123"), http


def test_facebook_reads_never_request_access_token():
    client, http = _meta_client({"data": [], "account_id": "123"})
    client.get_ad_account_info()
    client.list_account_campaigns(limit=5, after="abc")
    client.list_account_ad_sets(campaign_id="9")
    client.list_account_ads(ad_set_id="8")
    client.list_account_creatives()
    client.list_account_custom_audiences()
    client.get_campaign_info("1")
    client.get_ad_set_info("2")
    client.get_ad_info("3")
    client.get_insights_report(level="campaign", since=date(2026, 1, 1), until=date(2026, 1, 31))
    paths = []
    for call in http.call.call_args_list:
        method, path = call.args[:2]
        assert method == "GET"
        params = call.kwargs.get("params") or {}
        assert "access_token" not in params.get("fields", ""), call
        assert "page" not in params.get("fields", "").split(","), call
        paths.append(path)
    assert paths == [
        "act_123",
        "act_123/campaigns",
        "act_123/adsets",
        "act_123/ads",
        "act_123/adcreatives",
        "act_123/customaudiences",
        "1",
        "2",
        "3",
        "act_123/insights",
    ]


def test_facebook_insights_report_stays_on_the_account_edge():
    client, http = _meta_client()
    client.get_insights_report(campaign_id="77", ad_id="78", level="ad", date_preset="last_7d", time_increment="daily")
    call = http.call.call_args
    assert call.args[1] == "act_123/insights"
    params = call.kwargs["params"]
    assert params["level"] == "ad"
    assert params["date_preset"] == "last_7d"
    assert params["time_increment"] == "1"
    assert json.loads(params["filtering"]) == [
        {"field": "campaign.id", "operator": "EQUAL", "value": "77"},
        {"field": "ad.id", "operator": "EQUAL", "value": "78"},
    ]


def test_facebook_insights_report_takes_no_object_id():
    from bapp_connectors.providers.ads.facebook.client import MetaAdsClient

    assert "object_id" not in inspect.signature(MetaAdsClient.get_insights_report).parameters


@pytest.mark.parametrize("bad", ["act_999", "me", "123abc", "1 2", "", "١٢٣"])
@pytest.mark.parametrize(
    "call",
    [
        lambda c, v: c.get_campaign_info(v),
        lambda c, v: c.get_ad_set_info(v),
        lambda c, v: c.get_ad_info(v),
        lambda c, v: c.get_insights_report(campaign_id=v),
        lambda c, v: c.get_insights_report(ad_set_id=v),
        lambda c, v: c.get_insights_report(ad_id=v),
        lambda c, v: c.list_account_ad_sets(campaign_id=v or "x"),
        lambda c, v: c.list_account_ads(ad_set_id=v or "x"),
    ],
)
def test_facebook_refuses_non_numeric_ids(call, bad):
    client, http = _meta_client({"account_id": "123"})
    with pytest.raises(ValidationError):
        call(client, bad)
    http.call.assert_not_called()


@pytest.mark.parametrize("method", ["get_campaign_info", "get_ad_set_info", "get_ad_info"])
def test_facebook_object_reads_refuse_objects_of_another_account(method):
    client, http = _meta_client({"id": "5", "name": "x", "account_id": "999"})
    with pytest.raises(ValidationError):
        getattr(client, method)("5")
    assert "account_id" in http.call.call_args.kwargs["params"]["fields"].split(",")

    client, _http = _meta_client({"id": "5", "name": "x"})  # no account_id at all: refused too
    with pytest.raises(ValidationError):
        getattr(client, method)("5")

    client, _http = _meta_client({"id": "5", "name": "x", "account_id": "123"})
    assert getattr(client, method)("5")["id"] == "5"


def test_facebook_wrappers_drop_paging_urls_keep_cursors():
    envelope = {
        "data": [{"id": "1"}],
        "paging": {
            "cursors": {"before": "b", "after": "a"},
            "next": "https://graph.facebook.com/v19.0/act_123/campaigns?access_token=EAAB&after=a",
            "previous": "https://graph.facebook.com/v19.0/act_123/campaigns?access_token=EAAB&before=b",
        },
    }
    for call in (
        lambda c: c.list_account_campaigns(),
        lambda c: c.list_account_ad_sets(),
        lambda c: c.list_account_ads(),
        lambda c: c.list_account_creatives(),
        lambda c: c.list_account_custom_audiences(),
        lambda c: c.get_insights_report(),
    ):
        client, _http = _meta_client(json.loads(json.dumps(envelope)))
        out = call(client)
        assert out["paging"] == {"cursors": {"before": "b", "after": "a"}, "has_next": True}
        assert "access_token" not in repr(out)


def test_facebook_wrappers_drop_nested_paging_urls_and_report_the_last_page():
    envelope = {
        "data": [
            {
                "id": "1",
                "ads": {
                    "data": [],
                    "paging": {"next": "https://graph.facebook.com/v19.0/1/ads?access_token=EAAB&after=x"},
                },
            }
        ],
        "paging": {"cursors": {"before": "b", "after": "a"}},
    }
    client, _http = _meta_client(envelope)
    out = client.list_account_campaigns()
    assert "access_token" not in repr(out)
    assert out["paging"] == {"cursors": {"before": "b", "after": "a"}, "has_next": False}
    assert out["data"][0]["ads"]["paging"] == {"cursors": {}, "has_next": True}


# ── Google: GAQL allow-list ──


def _google_client():
    from bapp_connectors.providers.ads.google.client import GoogleAdsClient

    http = MagicMock()
    http.call.return_value = {"results": []}
    return GoogleAdsClient(http, developer_token="d", access_token="t", customer_id="123-456-7890"), http


@pytest.mark.parametrize(
    "query",
    [
        "SELECT campaign.id, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS",
        "SELECT campaign.id FROM campaign",
        "select ad_group.id from ad_group order by ad_group.id limit 5",
        "SELECT campaign.id FROM campaign\nWHERE campaign.status = 'ENABLED'",
        "SELECT customer.id FROM customer PARAMETERS include_drafts=true",
    ],
)
def test_google_run_report_allows_a_select_on_one_allowed_resource(query):
    client, http = _google_client()
    client.run_report(query)
    call = http.call.call_args
    assert call.args[:2] == ("POST", "customers/1234567890/googleAds:search")


@pytest.mark.parametrize(
    "query",
    [
        "SELECT customer_user_access.email_address FROM customer_user_access",
        "SELECT third_party_app_analytics_link.shareable_link_id FROM third_party_app_analytics_link",
        "SELECT asset.lead_form_asset.delivery_methods FROM asset",
        "SELECT ad_group_ad_asset_view.asset FROM ad_group_ad_asset_view WHERE asset.lead_form_asset.x = 1",
        "SELECT campaign.id FROM campaign WHERE campaign.name = 'x FROM customer_user_access'",
        "SELECT campaign.id FROM campaign, customer_user_access",
        "SELECT campaign.id FROM campaign ,customer_user_access",
        "SELECT campaign.id FROM campaign2",
        "SELECT campaign.id FROM campaign_x",
        "SELECT campaign.id FROM campaignWHERE campaign.id = 1",
        "campaign.id FROM campaign",
        "",
    ],
)
def test_google_run_report_refuses(query):
    client, http = _google_client()
    with pytest.raises(ValidationError):
        client.run_report(query)
    http.call.assert_not_called()


# ── LinkedIn: analytics pinned to the account, fixed fields ──


def _linkedin_client():
    from bapp_connectors.providers.ads.linkedin.client import LinkedInAdsClient

    http = MagicMock()
    http.call.return_value = {"elements": []}
    return LinkedInAdsClient(http, access_token="t", account_id="555", version="202401"), http


def test_linkedin_analytics_report_is_account_scoped():
    client, http = _linkedin_client()
    client.get_analytics_report(date(2026, 1, 1), date(2026, 1, 31), pivot="CAMPAIGN", campaign_id="7")
    path = http.call.call_args.args[1]
    assert path.startswith("adAnalytics?q=analytics&pivot=CAMPAIGN&")
    assert "accounts=List(urn%3Ali%3AsponsoredAccount%3A555)" in path
    assert "campaigns=List(urn%3Ali%3AsponsoredCampaign%3A7)" in path
    assert "dateRange=(start:(year:2026,month:1,day:1),end:(year:2026,month:1,day:31))" in path


def test_linkedin_accepts_ids_in_its_format():
    client, http = _linkedin_client()
    client.get_campaign_group("11")
    client.get_campaign("12")
    client.get_creative("urn:li:sponsoredCreative:13")
    client.list_campaigns(campaign_group_urn="urn:li:sponsoredCampaignGroup:11")
    client.list_creatives(campaign_urn="urn:li:sponsoredCampaign:12")
    client.get_analytics_report(date(2026, 1, 1), campaign_group_id="11")
    assert http.call.call_count == 6


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.get_campaign_group("7&x=1"),
        lambda c: c.get_campaign_group("urn:li:sponsoredCampaignGroup:7"),
        lambda c: c.get_campaign("7,8"),
        lambda c: c.get_campaign("(7)"),
        lambda c: c.get_campaign("١٢"),
        lambda c: c.get_campaign("%2Fme"),
        lambda c: c.get_creative("13"),
        lambda c: c.get_creative("urn:li:sponsoredCreative:13&x=1"),
        lambda c: c.get_creative("urn:li:person:1"),
        lambda c: c.list_campaigns(campaign_group_urn="urn:li:sponsoredCampaign:1"),
        lambda c: c.list_creatives(campaign_urn="urn:li:sponsoredCampaign:1)"),
        lambda c: c.get_analytics_report(date(2026, 1, 1), campaign_id="7&x=1"),
        lambda c: c.get_analytics_report(date(2026, 1, 1), campaign_group_id="x"),
    ],
)
def test_linkedin_refuses_ids_outside_its_format(call):
    client, http = _linkedin_client()
    with pytest.raises(ValidationError):
        call(client)
    http.call.assert_not_called()


# ── Pinterest: ids in the path ──


def _pinterest_client():
    from bapp_connectors.providers.ads.pinterest.client import PinterestAdsClient

    http = MagicMock()
    http.call.return_value = {}
    return PinterestAdsClient(http, ad_account_id="42"), http


def test_pinterest_accepts_plain_ids():
    client, http = _pinterest_client()
    client.get_campaign("626736533506")
    client.get_ad_group("2680059592705")
    client.get_ad("687195134316")
    assert [c.args[1] for c in http.call.call_args_list] == [
        "ad_accounts/42/campaigns/626736533506",
        "ad_accounts/42/ad_groups/2680059592705",
        "ad_accounts/42/ads/687195134316",
    ]


@pytest.mark.parametrize("bad", ["1&x=2", "%2F..%2Fuser_account", "1:2", "(1)", "1,2", "", "1 2"])
@pytest.mark.parametrize("method", ["get_campaign", "get_ad_group", "get_ad"])
def test_pinterest_refuses_ids_with_path_or_query_characters(method, bad):
    client, http = _pinterest_client()
    with pytest.raises(ValidationError):
        getattr(client, method)(bad)
    http.call.assert_not_called()
