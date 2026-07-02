"""
LinkedIn Ads adapter — implements AdsPort against the LinkedIn Marketing API.

HIERARCHY MAPPING — LinkedIn's hierarchy is Campaign Groups → Campaigns →
Creatives, which normalizes onto the framework's three levels as:

    AdCampaign  ↔  LinkedIn **campaign group**  (budget/schedule container)
    AdGroup     ↔  LinkedIn **campaign**        (targeting, budget, bidding)
    Ad          ↔  LinkedIn **creative**        (references an organic post)

Money crosses the boundary as Decimals in currency units and becomes
LinkedIn ``{"amount", "currencyCode"}`` records in the mappers. LinkedIn has
no hard delete: ``AdEntityStatus.DELETED`` maps to ARCHIVED.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlencode

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
from bapp_connectors.core.http import NoAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.linkedin.client import LinkedInAdsClient, encode_urn
from bapp_connectors.providers.ads.linkedin.manifest import manifest
from bapp_connectors.providers.ads.linkedin.mappers import (
    ad_from_creative,
    ad_group_from_campaign,
    campaign_from_group,
    campaign_group_patch,
    campaign_group_to_payload,
    campaign_patch,
    campaign_to_payload,
    creative_patch,
    creative_to_payload,
    insights_from_row,
    status_to_linkedin,
    urn_tail,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

INSIGHTS_PIVOT: dict[AdInsightsLevel, str] = {
    AdInsightsLevel.ACCOUNT: "ACCOUNT",
    AdInsightsLevel.CAMPAIGN: "CAMPAIGN_GROUP",
    AdInsightsLevel.AD_GROUP: "CAMPAIGN",
    AdInsightsLevel.AD: "CREATIVE",
}

INSIGHTS_FIELDS = "impressions,clicks,costInLocalCurrency,externalWebsiteConversions,dateRange,pivotValues"


def _restli_date(value: datetime) -> str:
    """Format a datetime as a Restli date record: (year:2026,month:6,day:1)."""
    return f"(year:{value.year},month:{value.month},day:{value.day})"


class LinkedInAdsAdapter(AdsPort, OAuthCapability):
    """
    LinkedIn Marketing API adapter.

    Implements AdsPort on the normalized hierarchy — **AdCampaign is a
    LinkedIn campaign group, AdGroup is a LinkedIn campaign, Ad is a LinkedIn
    creative** (see the module docstring). LinkedIn particularities:

    - Creatives reference organic posts: create_ad requires a post URN
      (e.g. urn:li:share:*) as the content reference — there is no
      CreativeUploadCapability.
    - Writes are Restli PARTIAL_UPDATE patches; creates return the new id in
      the ``x-restli-id`` response header.
    - No hard delete: DELETED maps to ARCHIVED.

    Implements OAuthCapability: LinkedIn OAuth2 authorization code flow with
    refresh-token support (refresh tokens are only issued to approved apps —
    their absence is tolerated).
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
        self.config = manifest.settings.apply_defaults(config or {})
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")
        self.ad_account_id = str(credentials.get("ad_account_id", ""))

        if http_client is None:
            # Auth + protocol headers are built per call by LinkedInAdsClient, hence NoAuth.
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=NoAuth(),
                provider_name="linkedin_ads",
            )

        self.client = LinkedInAdsClient(
            http_client=http_client,
            access_token=credentials.get("access_token", ""),
            account_id=self.ad_account_id,
            version=str(self.config.get("linkedin_version", "202405")),
        )

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self.credentials.get("access_token") and self.ad_account_id:
            return True
        # client_id + client_secret alone are enough to run the OAuth flow.
        return bool(self._client_id and self._client_secret)

    def test_connection(self) -> ConnectionTestResult:
        try:
            account = self.client.get_account()
            name = account.get("name", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to LinkedIn ad account '{name}' (id {self.ad_account_id})",
                details=account,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(scopes),
        }
        return f"{_LINKEDIN_AUTH_URL}?{urlencode(params)}"

    def _tokens_from_response(self, data: dict, fallback_refresh: str = "") -> OAuthTokens:
        """Build OAuthTokens from a LinkedIn token response.

        LinkedIn only issues refresh tokens to approved marketing partners —
        an absent ``refresh_token`` is tolerated (``fallback_refresh`` keeps
        the current one on refresh).
        """
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            refresh_token=data.get("refresh_token", "") or fallback_refresh,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "access_token": access_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            },
        )

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        data = response if isinstance(response, dict) else {}
        return self._tokens_from_response(data)

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            _LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        data = response if isinstance(response, dict) else {}
        return self._tokens_from_response(data, fallback_refresh=refresh_token)

    # ── Shared helpers ──

    @staticmethod
    def _paginate(response: dict, mapper: Callable[[dict], object]) -> PaginatedResult:
        """Map a Restli list envelope ({"elements": [...], "metadata": {"nextPageToken": ...}})."""
        items = [mapper(element) for element in response.get("elements", [])]
        cursor = (response.get("metadata") or {}).get("nextPageToken")
        return PaginatedResult(items=items, cursor=cursor, has_more=bool(cursor))

    @staticmethod
    def _campaign_group_urn(campaign_id: str) -> str:
        return f"urn:li:sponsoredCampaignGroup:{campaign_id}"

    @staticmethod
    def _campaign_urn(ad_group_id: str) -> str:
        return f"urn:li:sponsoredCampaign:{ad_group_id}"

    @staticmethod
    def _creative_urn(ad_id: str) -> str:
        ad_id = str(ad_id)
        return ad_id if ad_id.startswith("urn:") else f"urn:li:sponsoredCreative:{ad_id}"

    # ── Campaigns (LinkedIn campaign groups) ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        response = self.client.list_campaign_groups(page_token=cursor)
        return self._paginate(response, campaign_from_group)

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        return campaign_from_group(self.client.get_campaign_group(campaign_id))

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        payload = campaign_group_to_payload(campaign, self.client.account_urn)
        created_id = self.client.create_campaign_group(payload)
        return self.get_campaign(urn_tail(created_id))

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        self.client.update_campaign_group(campaign_id, campaign_group_patch(changes))
        return self.get_campaign(campaign_id)

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        self.client.update_campaign_group(campaign_id, {"status": status_to_linkedin(status)})
        return self.get_campaign(campaign_id)

    # ── Ad groups (LinkedIn campaigns) ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        group_urn = self._campaign_group_urn(campaign_id) if campaign_id else None
        response = self.client.list_campaigns(campaign_group_urn=group_urn, page_token=cursor)
        return self._paginate(response, ad_group_from_campaign)

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        return ad_group_from_campaign(self.client.get_campaign(ad_group_id))

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        payload = campaign_to_payload(ad_group, self.client.account_urn)
        created_id = self.client.create_campaign(payload)
        return self.get_ad_group(urn_tail(created_id))

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        self.client.update_campaign(ad_group_id, campaign_patch(changes))
        return self.get_ad_group(ad_group_id)

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        self.client.update_campaign(ad_group_id, {"status": status_to_linkedin(status)})
        return self.get_ad_group(ad_group_id)

    # ── Ads (LinkedIn creatives) ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        campaign_urn = self._campaign_urn(ad_group_id) if ad_group_id else None
        response = self.client.list_creatives(campaign_urn=campaign_urn, page_token=cursor)
        return self._paginate(response, ad_from_creative)

    def get_ad(self, ad_id: str) -> Ad:
        return ad_from_creative(self.client.get_creative(self._creative_urn(ad_id)))

    def create_ad(self, ad: Ad) -> Ad:
        payload = creative_to_payload(ad, self._campaign_urn(ad.ad_group_id))
        created_id = self.client.create_creative(payload)
        return self.get_ad(urn_tail(created_id))

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        self.client.update_creative(self._creative_urn(ad_id), creative_patch(changes))
        return self.get_ad(ad_id)

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        self.client.update_creative(self._creative_urn(ad_id), {"intendedStatus": status_to_linkedin(status)})
        return self.get_ad(ad_id)

    # ── Universal insights ──

    def get_insights(
        self,
        level: AdInsightsLevel,
        entity_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AdInsights]:
        level = AdInsightsLevel(level)
        until = until or datetime.now(UTC)
        since = since or until - timedelta(days=30)

        params: dict = {
            "q": "analytics",
            "pivot": INSIGHTS_PIVOT[level],
            "dateRange": f"(start:{_restli_date(since)},end:{_restli_date(until)})",
            "timeGranularity": "ALL",
            "accounts": f"List({encode_urn(self.client.account_urn)})",
            "fields": INSIGHTS_FIELDS,
        }
        if entity_id and level == AdInsightsLevel.CAMPAIGN:
            params["campaignGroups"] = f"List({encode_urn(self._campaign_group_urn(entity_id))})"
        elif entity_id and level == AdInsightsLevel.AD_GROUP:
            params["campaigns"] = f"List({encode_urn(self._campaign_urn(entity_id))})"
        elif entity_id and level == AdInsightsLevel.AD:
            params["creatives"] = f"List({encode_urn(self._creative_urn(entity_id))})"

        response = self.client.analytics(params)
        return [insights_from_row(row, level) for row in response.get("elements", [])]
