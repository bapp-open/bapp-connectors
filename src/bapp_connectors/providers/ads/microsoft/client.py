"""
Bing Ads API v13 SOAP client — raw HTTP/XML calls only, no business logic.

The Bing Ads API is SOAP-only. Rather than pulling in a SOAP library (zeep,
suds), this client hand-rolls the minimal SOAP 1.1 envelopes the Campaign
Management and Reporting services need and parses responses with
``xml.etree.ElementTree``. Response elements are matched by local name
(namespace-agnostic) because Bing mixes the service namespace with the
serialization-arrays and xsi namespaces.

Simplifications (unit tests are mocked; documented for real-API hardening):
- Request element order follows the alphabetical-ish order of the v13 WSDL
  for the subset of fields we send (SOAP is order-sensitive); optional fields
  the framework doesn't model are omitted.
- ``add_ads``/``update_ads`` always emit ``i:type="ResponsiveSearchAd"`` —
  legacy ad formats are read (Title/Text) but never written.
- ``PartialErrors`` are only inspected when an Add* call returns no IDs;
  per-item partial failures on bulk calls are otherwise ignored.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from bapp_connectors.core.errors import ProviderError
from bapp_connectors.providers.ads.microsoft.errors import classify_soap_fault

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
CAMPAIGN_NS = "https://bingads.microsoft.com/CampaignManagement/v13"
REPORTING_NS = "https://bingads.microsoft.com/Reporting/v13"
ARRAYS_NS = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

NS = {"s": SOAP_NS, "v13": CAMPAIGN_NS}

REPORTING_URL = "https://reporting.api.bingads.microsoft.com/Api/Advertiser/Reporting/v13/ReportingService.svc"

# SOAP element order matters — these follow the v13 WSDL order for the fields we send.
CAMPAIGN_FIELD_ORDER = ["BudgetType", "CampaignType", "DailyBudget", "Id", "Name", "Status", "TimeZone"]
AD_GROUP_FIELD_ORDER = ["CpcBid", "EndDate", "Id", "Name", "StartDate", "Status"]
AD_FIELD_ORDER = ["Descriptions", "FinalUrls", "Headlines", "Id", "Status"]

# Campaign types requested on reads; DynamicSearchAds is omitted (unmapped objective).
CAMPAIGN_TYPES = "Search Shopping Audience PerformanceMax"
AD_TYPES = ["ResponsiveSearch", "ExpandedText", "Text"]


# ── Namespace-agnostic parsing helpers ──


def local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def find_first(element: ET.Element, name: str) -> ET.Element | None:
    """Find the first descendant (or self) whose local tag name matches."""
    for el in element.iter():
        if local_name(el.tag) == name:
            return el
    return None


def find_all(element: ET.Element, name: str) -> list[ET.Element]:
    """Find all descendants (or self) whose local tag name matches."""
    return [el for el in element.iter() if local_name(el.tag) == name]


def text_of(element: ET.Element, name: str, default: str = "") -> str:
    """Text content of the first matching descendant ('' for nil/absent elements)."""
    el = find_first(element, name)
    if el is None or el.text is None:
        return default
    return el.text


# ── XML building helpers ──


def _tag(name: str, value) -> str:
    return f"<{name}>{escape(str(value))}</{name}>"


def _string_array(name: str, values: list[str]) -> str:
    items = "".join(f"<a:string>{escape(str(v))}</a:string>" for v in values)
    return f'<{name} xmlns:a="{ARRAYS_NS}">{items}</{name}>'


def _asset_links(name: str, texts: list[str]) -> str:
    """Responsive search ad Headlines/Descriptions: AssetLink > Asset(TextAsset) > Text."""
    links = "".join(
        f'<AssetLink><Asset i:type="TextAsset" xmlns:i="{XSI_NS}"><Text>{escape(str(t))}</Text></Asset></AssetLink>'
        for t in texts
    )
    return f"<{name}>{links}</{name}>"


def _nested(name: str, mapping: dict) -> str:
    """Nested complex element (e.g. CpcBid > Amount, StartDate > Day/Month/Year)."""
    inner = "".join(_tag(key, value) for key, value in mapping.items())
    return f"<{name}>{inner}</{name}>"


def _fields_xml(data: dict, order: list[str]) -> str:
    """Serialize an entity dict in the WSDL field order, skipping absent/None fields."""
    parts = []
    for key in order:
        value = data.get(key)
        if value is None:
            continue
        if key == "FinalUrls":
            parts.append(_string_array(key, value))
        elif key in ("Headlines", "Descriptions"):
            parts.append(_asset_links(key, value))
        elif isinstance(value, dict):
            parts.append(_nested(key, value))
        else:
            parts.append(_tag(key, value))
    return "".join(parts)


class MicrosoftAdsClient:
    """
    Low-level Bing Ads API v13 SOAP client.

    Builds request envelopes, POSTs them, and parses responses into plain
    dicts with the original PascalCase field names. Normalization to DTOs
    happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        developer_token: str,
        access_token: str,
        customer_id: str,
        account_id: str,
    ):
        self.http = http_client
        self.developer_token = developer_token
        self.access_token = access_token
        self.customer_id = str(customer_id)
        self.account_id = str(account_id)

    # ── SOAP plumbing ──

    def _call(self, action: str, body_xml: str, service_url: str = "", ns: str = CAMPAIGN_NS) -> ET.Element:
        """POST one SOAP request and return the parsed ``s:Body`` element.

        ``service_url`` defaults to '' (the client base_url — the Campaign
        Management service); reporting calls pass the absolute reporting URL.
        SOAP faults and HTTP errors are classified via ``classify_soap_fault``.
        """
        envelope = (
            f'<s:Envelope xmlns:s="{SOAP_NS}">'
            f'<s:Header xmlns="{ns}">'
            f"{_tag('AuthenticationToken', self.access_token)}"
            f"{_tag('DeveloperToken', self.developer_token)}"
            f"{_tag('CustomerId', self.customer_id)}"
            f"{_tag('CustomerAccountId', self.account_id)}"
            "</s:Header>"
            f"<s:Body>{body_xml}</s:Body>"
            "</s:Envelope>"
        )
        response = self.http.call(
            "POST",
            service_url,
            data=envelope.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": action},
            direct_response=True,
        )
        status = getattr(response, "status_code", None)
        text = getattr(response, "text", "") or ""
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            classify_soap_fault(text, status)
        if not response.ok or find_first(root, "Fault") is not None:
            classify_soap_fault(text, status)
        body = find_first(root, "Body")
        if body is None:
            raise ProviderError(f"Microsoft Ads SOAP response for {action} has no Body element.")
        return body

    def _parse_ids(self, body: ET.Element, container_name: str) -> list[str]:
        """Parse an Add* response ID list (``<a:long>`` array). Classifies batch errors when empty."""
        container = find_first(body, container_name)
        ids = []
        if container is not None:
            ids = [el.text for el in container.iter() if local_name(el.tag) == "long" and el.text]
        if not ids and find_first(body, "BatchError") is not None:
            classify_soap_fault(ET.tostring(body, encoding="unicode"), None)
        return ids

    @staticmethod
    def _parse_date(element: ET.Element | None) -> dict | None:
        """Parse a Bing ``Date`` complex type into {"Day", "Month", "Year"} (None when nil)."""
        if element is None:
            return None
        day, month, year = text_of(element, "Day"), text_of(element, "Month"), text_of(element, "Year")
        if not (day and month and year):
            return None
        return {"Day": day, "Month": month, "Year": year}

    # ── Campaigns ──

    def get_campaigns(self) -> list[dict]:
        """GetCampaignsByAccountId — all campaigns in the account."""
        body_xml = (
            f'<GetCampaignsByAccountIdRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('AccountId', self.account_id)}"
            f"{_tag('CampaignType', CAMPAIGN_TYPES)}"
            "</GetCampaignsByAccountIdRequest>"
        )
        body = self._call("GetCampaignsByAccountId", body_xml)
        return [
            {
                "Id": text_of(el, "Id"),
                "Name": text_of(el, "Name"),
                "Status": text_of(el, "Status"),
                "BudgetType": text_of(el, "BudgetType"),
                "DailyBudget": text_of(el, "DailyBudget"),
                "TimeZone": text_of(el, "TimeZone"),
                "CampaignType": text_of(el, "CampaignType"),
            }
            for el in find_all(body, "Campaign")
        ]

    def add_campaigns(self, campaigns: list[dict]) -> list[str]:
        """AddCampaigns — returns the new campaign IDs."""
        items = "".join(f"<Campaign>{_fields_xml(c, CAMPAIGN_FIELD_ORDER)}</Campaign>" for c in campaigns)
        body_xml = (
            f'<AddCampaignsRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('AccountId', self.account_id)}"
            f"<Campaigns>{items}</Campaigns>"
            "</AddCampaignsRequest>"
        )
        body = self._call("AddCampaigns", body_xml)
        return self._parse_ids(body, "CampaignIds")

    def update_campaigns(self, campaigns: list[dict]) -> None:
        """UpdateCampaigns — each dict must include ``Id``."""
        items = "".join(f"<Campaign>{_fields_xml(c, CAMPAIGN_FIELD_ORDER)}</Campaign>" for c in campaigns)
        body_xml = (
            f'<UpdateCampaignsRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('AccountId', self.account_id)}"
            f"<Campaigns>{items}</Campaigns>"
            "</UpdateCampaignsRequest>"
        )
        self._call("UpdateCampaigns", body_xml)

    # ── Ad groups ──

    def get_ad_groups(self, campaign_id: str) -> list[dict]:
        """GetAdGroupsByCampaignId — all ad groups in one campaign."""
        body_xml = (
            f'<GetAdGroupsByCampaignIdRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('CampaignId', campaign_id)}"
            "</GetAdGroupsByCampaignIdRequest>"
        )
        body = self._call("GetAdGroupsByCampaignId", body_xml)
        groups = []
        for el in find_all(body, "AdGroup"):
            cpc_bid = find_first(el, "CpcBid")
            groups.append(
                {
                    "Id": text_of(el, "Id"),
                    "Name": text_of(el, "Name"),
                    "Status": text_of(el, "Status"),
                    "CpcBid": text_of(cpc_bid, "Amount") if cpc_bid is not None else None,
                    "StartDate": self._parse_date(find_first(el, "StartDate")),
                    "EndDate": self._parse_date(find_first(el, "EndDate")),
                }
            )
        return groups

    def add_ad_groups(self, campaign_id: str, ad_groups: list[dict]) -> list[str]:
        """AddAdGroups — returns the new ad group IDs."""
        items = "".join(f"<AdGroup>{_fields_xml(g, AD_GROUP_FIELD_ORDER)}</AdGroup>" for g in ad_groups)
        body_xml = (
            f'<AddAdGroupsRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('CampaignId', campaign_id)}"
            f"<AdGroups>{items}</AdGroups>"
            "</AddAdGroupsRequest>"
        )
        body = self._call("AddAdGroups", body_xml)
        return self._parse_ids(body, "AdGroupIds")

    def update_ad_groups(self, campaign_id: str, ad_groups: list[dict]) -> None:
        """UpdateAdGroups — each dict must include ``Id``."""
        items = "".join(f"<AdGroup>{_fields_xml(g, AD_GROUP_FIELD_ORDER)}</AdGroup>" for g in ad_groups)
        body_xml = (
            f'<UpdateAdGroupsRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('CampaignId', campaign_id)}"
            f"<AdGroups>{items}</AdGroups>"
            "</UpdateAdGroupsRequest>"
        )
        self._call("UpdateAdGroups", body_xml)

    # ── Ads ──

    def get_ads(self, ad_group_id: str) -> list[dict]:
        """GetAdsByAdGroupId — responsive search, expanded text, and text ads in one ad group."""
        ad_types = "".join(f"<AdType>{t}</AdType>" for t in AD_TYPES)
        body_xml = (
            f'<GetAdsByAdGroupIdRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('AdGroupId', ad_group_id)}"
            f"<AdTypes>{ad_types}</AdTypes>"
            "</GetAdsByAdGroupIdRequest>"
        )
        body = self._call("GetAdsByAdGroupId", body_xml)
        ads_container = find_first(body, "Ads")
        elements = list(ads_container) if ads_container is not None else []
        return [self._parse_ad(el) for el in elements if local_name(el.tag) == "Ad"]

    @staticmethod
    def _parse_ad(el: ET.Element) -> dict:
        final_urls_el = find_first(el, "FinalUrls")
        final_urls = (
            [s.text for s in final_urls_el.iter() if local_name(s.tag) == "string" and s.text]
            if final_urls_el is not None
            else []
        )

        def asset_texts(name: str) -> list[str]:
            container = find_first(el, name)
            if container is None:
                return []
            return [t.text for t in container.iter() if local_name(t.tag) == "Text" and t.text]

        headlines = asset_texts("Headlines")
        descriptions = asset_texts("Descriptions")
        # Only read legacy Title/Text when this isn't a responsive search ad —
        # a bare "Text" lookup would otherwise match a TextAsset's Text.
        legacy = not headlines and not descriptions
        return {
            "Id": text_of(el, "Id"),
            "Type": text_of(el, "Type"),
            "Status": text_of(el, "Status"),
            "FinalUrls": final_urls,
            "Headlines": headlines,
            "Descriptions": descriptions,
            "Title": text_of(el, "Title") if legacy else "",
            "Text": text_of(el, "Text") if legacy else "",
        }

    def add_ads(self, ad_group_id: str, ads: list[dict]) -> list[str]:
        """AddAds — always sends responsive search ads. Returns the new ad IDs."""
        items = "".join(
            f'<Ad i:type="ResponsiveSearchAd" xmlns:i="{XSI_NS}">{_fields_xml(ad, AD_FIELD_ORDER)}</Ad>' for ad in ads
        )
        body_xml = (
            f'<AddAdsRequest xmlns="{CAMPAIGN_NS}">{_tag("AdGroupId", ad_group_id)}<Ads>{items}</Ads></AddAdsRequest>'
        )
        body = self._call("AddAds", body_xml)
        return self._parse_ids(body, "AdIds")

    def update_ads(self, ad_group_id: str, ads: list[dict]) -> None:
        """UpdateAds — each dict must include ``Id``."""
        items = "".join(
            f'<Ad i:type="ResponsiveSearchAd" xmlns:i="{XSI_NS}">{_fields_xml(ad, AD_FIELD_ORDER)}</Ad>' for ad in ads
        )
        body_xml = (
            f'<UpdateAdsRequest xmlns="{CAMPAIGN_NS}">'
            f"{_tag('AdGroupId', ad_group_id)}"
            f"<Ads>{items}</Ads>"
            "</UpdateAdsRequest>"
        )
        self._call("UpdateAds", body_xml)

    # ── Reporting service ──

    def submit_report(self, report_request_xml: str) -> str:
        """SubmitGenerateReport — returns the ReportRequestId to poll."""
        body_xml = (
            f'<SubmitGenerateReportRequest xmlns="{REPORTING_NS}">{report_request_xml}</SubmitGenerateReportRequest>'
        )
        body = self._call("SubmitGenerateReport", body_xml, service_url=REPORTING_URL, ns=REPORTING_NS)
        request_id = text_of(body, "ReportRequestId")
        if not request_id:
            raise ProviderError("Microsoft Ads SubmitGenerateReport returned no ReportRequestId.")
        return request_id

    def poll_report(self, report_request_id: str) -> tuple[str, str]:
        """PollGenerateReport — returns (Status, ReportDownloadUrl)."""
        body_xml = (
            f'<PollGenerateReportRequest xmlns="{REPORTING_NS}">'
            f"{_tag('ReportRequestId', report_request_id)}"
            "</PollGenerateReportRequest>"
        )
        body = self._call("PollGenerateReport", body_xml, service_url=REPORTING_URL, ns=REPORTING_NS)
        return text_of(body, "Status"), text_of(body, "ReportDownloadUrl")

    def download_report(self, url: str) -> bytes:
        """Download the generated report ZIP from the (pre-signed) download URL."""
        response = self.http.call("GET", url, direct_response=True)
        if not getattr(response, "ok", False):
            raise ProviderError(
                f"Microsoft Ads report download failed: {getattr(response, 'status_code', '?')}",
                status_code=getattr(response, "status_code", None),
            )
        return response.content
