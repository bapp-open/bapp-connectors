"""
Microsoft Ads (Bing Ads) advertising adapter — implements AdsPort.

Uses the Bing Ads API v13 SOAP surface: entity CRUD goes through the
Campaign Management service, insights through the Reporting service's
submit / poll / download-ZIP flow (run synchronously with a short poll cap).

Normalized mapping: Bing "campaign" -> AdCampaign, "ad group" -> AdGroup,
"ad" -> Ad. Bing particularities:

- Reads are scoped per parent: ad groups are fetched per campaign and ads
  per ad group (there is no account-wide listing), so ``list_ad_groups`` /
  ``list_ads`` require their parent id. Lookups by bare id (get_ad_group,
  set_ad_status, ...) resolve the parent from an in-memory cache populated
  by list/get/create calls, falling back to a full campaign -> ad group ->
  ad scan when the entity hasn't been seen yet.
- DELETED is a real status value on Bing (set via Update*), not a separate
  remove operation.
- OAuth token refresh is handled outside the adapter — pass a valid
  ``access_token`` credential.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.ads import (
    Ad,
    AdCampaign,
    AdEntityStatus,
    AdGroup,
    AdInsights,
    AdInsightsLevel,
)
from bapp_connectors.core.errors import ProviderError, ValidationError
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.microsoft.client import ARRAYS_NS, XSI_NS, MicrosoftAdsClient
from bapp_connectors.providers.ads.microsoft.errors import not_found
from bapp_connectors.providers.ads.microsoft.manifest import manifest
from bapp_connectors.providers.ads.microsoft.mappers import (
    ad_changes_to_ms,
    ad_from_ms,
    ad_group_changes_to_ms,
    ad_group_from_ms,
    ad_group_to_ms,
    ad_to_ms,
    campaign_changes_to_ms,
    campaign_from_ms,
    campaign_to_ms,
    insights_from_report_row,
    parse_report_csv,
)

if TYPE_CHECKING:
    from datetime import datetime

_MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
_MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

# ── Reporting service (insights) ──

# level -> (ReportRequest i:type, column element name, entity id column)
REPORT_REQUEST_TYPES = {
    AdInsightsLevel.ACCOUNT: ("AccountPerformanceReportRequest", "AccountPerformanceReportColumn", ""),
    AdInsightsLevel.CAMPAIGN: ("CampaignPerformanceReportRequest", "CampaignPerformanceReportColumn", "CampaignId"),
    AdInsightsLevel.AD_GROUP: ("AdGroupPerformanceReportRequest", "AdGroupPerformanceReportColumn", "AdGroupId"),
    AdInsightsLevel.AD: ("AdPerformanceReportRequest", "AdPerformanceReportColumn", "AdId"),
}

REPORT_METRIC_COLUMNS = ["Impressions", "Clicks", "Spend", "Ctr", "AverageCpc", "Conversions", "Revenue"]

MAX_REPORT_POLLS = 10
REPORT_POLL_DELAY_SECONDS = 1.0


class MicrosoftAdsAdapter(AdsPort, OAuthCapability):
    """
    Bing Ads API v13 SOAP adapter.

    Implements AdsPort: campaign / ad group / ad CRUD plus the universal
    insights interface (via the Reporting service). Simplifications:

    - Campaign Management Get* calls return everything in one shot — results
      are not paginated (cursor is always None).
    - Only responsive search ads are written; ad updates support status only
      (Bing RSAs are content-editable, but this adapter keeps parity with
      the other search providers — recreate the ad for content changes).
    - Insights use Aggregation=Summary: one row per entity over the period,
      no per-day breakdown.
    """

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self.config = manifest.settings.apply_defaults(config or {})

        if http_client is None:
            # SOAP auth lives in the envelope header built per call, hence NoAuth here.
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),
                provider_name="microsoft_ads",
            )

        self.client = MicrosoftAdsClient(
            http_client=http_client,
            developer_token=credentials.get("developer_token", ""),
            access_token=credentials.get("access_token", ""),
            customer_id=str(credentials.get("customer_id", "") or ""),
            account_id=str(credentials.get("account_id", "") or ""),
        )

        # Bing addresses ad groups per campaign and ads per ad group; these
        # caches let bare-id lookups skip the full hierarchy scan.
        self._campaign_of_ad_group: dict[str, str] = {}
        self._ad_group_of_ad: dict[str, str] = {}

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if not self.credentials.get("access_token"):
            # client_id + client_secret alone are enough to run the OAuth flow.
            return bool(self._client_id and self._client_secret)
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            campaigns = self.client.get_campaigns()
            return ConnectionTestResult(
                success=True,
                message=(f"Connected to Microsoft Ads account {self.client.account_id} ({len(campaigns)} campaigns)."),
                details={"account_id": self.client.account_id, "campaign_count": len(campaigns)},
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"{_MS_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _MS_TOKEN_URL,
            data={
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        refresh_tok = data.get("refresh_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_tok,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "access_token": access_token,
                    "refresh_token": refresh_tok,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _MS_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        data = response if isinstance(response, dict) else {}
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    # ── Internal helpers ──

    def _cache_ad_group(self, ad_group_id: str, campaign_id: str) -> None:
        self._campaign_of_ad_group[str(ad_group_id)] = str(campaign_id)

    def _cache_ad(self, ad_id: str, ad_group_id: str) -> None:
        self._ad_group_of_ad[str(ad_id)] = str(ad_group_id)

    def _find_ad_group(self, ad_group_id: str) -> tuple[dict, str]:
        """Locate an ad group by bare id, returning (raw ad group, campaign_id).

        Uses the ad_group -> campaign cache when possible; otherwise scans
        every campaign's ad groups (populating the cache along the way).
        """
        ad_group_id = str(ad_group_id)
        cached_campaign = self._campaign_of_ad_group.get(ad_group_id)
        if cached_campaign:
            for group in self.client.get_ad_groups(cached_campaign):
                if str(group["Id"]) == ad_group_id:
                    return group, cached_campaign
        for campaign in self.client.get_campaigns():
            campaign_id = str(campaign["Id"])
            for group in self.client.get_ad_groups(campaign_id):
                self._cache_ad_group(str(group["Id"]), campaign_id)
                if str(group["Id"]) == ad_group_id:
                    return group, campaign_id
        not_found("ad group", ad_group_id)

    def _find_ad(self, ad_id: str) -> tuple[dict, str]:
        """Locate an ad by bare id, returning (raw ad, ad_group_id).

        Uses the ad -> ad group cache when possible; otherwise scans the
        whole campaign -> ad group -> ad hierarchy (populating the caches).
        """
        ad_id = str(ad_id)
        cached_group = self._ad_group_of_ad.get(ad_id)
        if cached_group:
            for ad in self.client.get_ads(cached_group):
                if str(ad["Id"]) == ad_id:
                    return ad, cached_group
        for campaign in self.client.get_campaigns():
            campaign_id = str(campaign["Id"])
            for group in self.client.get_ad_groups(campaign_id):
                group_id = str(group["Id"])
                self._cache_ad_group(group_id, campaign_id)
                for ad in self.client.get_ads(group_id):
                    self._cache_ad(str(ad["Id"]), group_id)
                    if str(ad["Id"]) == ad_id:
                        return ad, group_id
        not_found("ad", ad_id)

    # ── Campaigns ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        campaigns = self.client.get_campaigns()
        return PaginatedResult(
            items=[campaign_from_ms(c) for c in campaigns],
            cursor=None,
            has_more=False,
        )

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        for campaign in self.client.get_campaigns():
            if str(campaign["Id"]) == str(campaign_id):
                return campaign_from_ms(campaign)
        not_found("campaign", campaign_id)

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        ids = self.client.add_campaigns([campaign_to_ms(campaign)])
        if not ids:
            raise ProviderError("Microsoft Ads AddCampaigns returned no campaign id.")
        return self.get_campaign(ids[0])

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        data = campaign_changes_to_ms(changes)
        data["Id"] = str(campaign_id)
        self.client.update_campaigns([data])
        return self.get_campaign(campaign_id)

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        return self.update_campaign(campaign_id, {"status": AdEntityStatus(status)})

    # ── Ad groups ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        if not campaign_id:
            raise ValidationError(
                "Microsoft Ads scopes ad groups per campaign (GetAdGroupsByCampaignId) — "
                "pass campaign_id; there is no account-wide ad group listing."
            )
        groups = self.client.get_ad_groups(campaign_id)
        for group in groups:
            self._cache_ad_group(str(group["Id"]), str(campaign_id))
        return PaginatedResult(
            items=[ad_group_from_ms(g, str(campaign_id)) for g in groups],
            cursor=None,
            has_more=False,
        )

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        group, campaign_id = self._find_ad_group(ad_group_id)
        return ad_group_from_ms(group, campaign_id)

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        if not ad_group.campaign_id:
            raise ValidationError("Microsoft Ads ad groups are created inside a campaign — set campaign_id.")
        ids = self.client.add_ad_groups(ad_group.campaign_id, [ad_group_to_ms(ad_group)])
        if not ids:
            raise ProviderError("Microsoft Ads AddAdGroups returned no ad group id.")
        self._cache_ad_group(ids[0], ad_group.campaign_id)
        return self.get_ad_group(ids[0])

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        data = ad_group_changes_to_ms(changes)
        _, campaign_id = self._find_ad_group(ad_group_id)
        data["Id"] = str(ad_group_id)
        self.client.update_ad_groups(campaign_id, [data])
        return self.get_ad_group(ad_group_id)

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        return self.update_ad_group(ad_group_id, {"status": AdEntityStatus(status)})

    # ── Ads ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        if not ad_group_id:
            raise ValidationError(
                "Microsoft Ads scopes ads per ad group (GetAdsByAdGroupId) — "
                "pass ad_group_id; there is no account-wide ad listing."
            )
        ads = self.client.get_ads(ad_group_id)
        for ad in ads:
            self._cache_ad(str(ad["Id"]), str(ad_group_id))
        return PaginatedResult(
            items=[ad_from_ms(ad, str(ad_group_id)) for ad in ads],
            cursor=None,
            has_more=False,
        )

    def get_ad(self, ad_id: str) -> Ad:
        ad, ad_group_id = self._find_ad(ad_id)
        return ad_from_ms(ad, ad_group_id)

    def create_ad(self, ad: Ad) -> Ad:
        if not ad.ad_group_id:
            raise ValidationError("Microsoft Ads ads are created inside an ad group — set ad_group_id.")
        ids = self.client.add_ads(ad.ad_group_id, [ad_to_ms(ad)])
        if not ids:
            raise ProviderError("Microsoft Ads AddAds returned no ad id.")
        self._cache_ad(ids[0], ad.ad_group_id)
        return self.get_ad(ids[0])

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        data = ad_changes_to_ms(changes)
        _, ad_group_id = self._find_ad(ad_id)
        data["Id"] = str(ad_id)
        self.client.update_ads(ad_group_id, [data])
        return self.get_ad(ad_id)

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        return self.update_ad(ad_id, {"status": AdEntityStatus(status)})

    # ── Universal insights (Reporting service) ──

    @staticmethod
    def _date_xml(value: datetime) -> str:
        return f"<Day>{value.day}</Day><Month>{value.month}</Month><Year>{value.year}</Year>"

    def _report_time_xml(self, since: datetime | None, until: datetime | None) -> str:
        if since and until:
            # WSDL order: CustomDateRangeEnd before CustomDateRangeStart.
            return (
                "<Time>"
                f"<CustomDateRangeEnd>{self._date_xml(until)}</CustomDateRangeEnd>"
                f"<CustomDateRangeStart>{self._date_xml(since)}</CustomDateRangeStart>"
                "</Time>"
            )
        # A single-ended range isn't expressible with Bing's Date pair; default period.
        return "<Time><PredefinedTime>LastSevenDays</PredefinedTime></Time>"

    def _report_scope_xml(self, level: AdInsightsLevel, entity_id: str | None) -> str:
        account_id = escape(self.client.account_id)
        parts = [f'<AccountIds xmlns:a="{ARRAYS_NS}"><a:long>{account_id}</a:long></AccountIds>']
        if entity_id and level == AdInsightsLevel.AD_GROUP:
            _, campaign_id = self._find_ad_group(entity_id)
            parts.append(
                "<AdGroups><AdGroupReportScope>"
                f"<AccountId>{account_id}</AccountId>"
                f"<AdGroupId>{escape(str(entity_id))}</AdGroupId>"
                f"<CampaignId>{escape(campaign_id)}</CampaignId>"
                "</AdGroupReportScope></AdGroups>"
            )
        elif entity_id and level == AdInsightsLevel.CAMPAIGN:
            parts.append(
                "<Campaigns><CampaignReportScope>"
                f"<AccountId>{account_id}</AccountId>"
                f"<CampaignId>{escape(str(entity_id))}</CampaignId>"
                "</CampaignReportScope></Campaigns>"
            )
        # Ad level has no report scope — entity_id is filtered client-side on the AdId column.
        return f"<Scope>{''.join(parts)}</Scope>"

    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        level = AdInsightsLevel(level)
        request_type, column_tag, id_column = REPORT_REQUEST_TYPES[level]
        columns = ([id_column] if id_column else []) + REPORT_METRIC_COLUMNS
        columns_xml = "".join(f"<{column_tag}>{c}</{column_tag}>" for c in columns)

        report_request = (
            f'<ReportRequest i:type="{request_type}" xmlns:i="{XSI_NS}">'
            "<Format>Csv</Format>"
            f"<ReportName>bapp-connectors {level.value} insights</ReportName>"
            "<Aggregation>Summary</Aggregation>"
            f"<Columns>{columns_xml}</Columns>"
            f"{self._report_scope_xml(level, entity_id)}"
            f"{self._report_time_xml(since, until)}"
            "</ReportRequest>"
        )

        request_id = self.client.submit_report(report_request)
        status, download_url = "", ""
        for _ in range(MAX_REPORT_POLLS):
            status, download_url = self.client.poll_report(request_id)
            if status in ("Success", "Error"):
                break
            time.sleep(REPORT_POLL_DELAY_SECONDS)
        if status == "Error":
            raise ProviderError(f"Microsoft Ads report generation failed (request {request_id}).")
        if status != "Success":
            raise ProviderError(
                f"Microsoft Ads report {request_id} still '{status or 'Pending'}' after {MAX_REPORT_POLLS} polls."
            )
        if not download_url:
            # Bing reports Success without a URL when the period has no data.
            return []

        content = self.client.download_report(download_url)
        rows = parse_report_csv(content, columns[0])
        currency = self.config.get("currency", "USD")
        insights = [
            insights_from_report_row(
                row,
                level,
                currency=currency,
                id_column=id_column,
                fallback_id=self.client.account_id,
                since=since,
                until=until,
            )
            for row in rows
        ]
        if entity_id and level == AdInsightsLevel.AD:
            insights = [row for row in insights if row.entity_id == str(entity_id)]
        return insights
