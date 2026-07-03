"""
Pinterest Ads adapter — implements AdsPort against the Pinterest API v5.

Manages the normalized campaign → ad group → ad hierarchy and reports
performance through the universal AdInsights DTO. Budgets and bids cross the
boundary as Decimals in currency units and are converted to/from Pinterest's
micro-currency integers by the mappers.

An ad promotes an existing Pin (``Ad.creative.id`` carries the pin_id), so
there is no CreativeUploadCapability. OAuthCapability drives the standard
Pinterest authorization-code flow with Basic-auth token calls.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
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
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.core.http import BearerAuth, ResilientHttpClient
from bapp_connectors.core.ports import AdsPort
from bapp_connectors.providers.ads.pinterest.client import PinterestAdsClient
from bapp_connectors.providers.ads.pinterest.errors import check_item
from bapp_connectors.providers.ads.pinterest.manifest import manifest
from bapp_connectors.providers.ads.pinterest.mappers import (
    ad_from_pinterest,
    ad_group_from_pinterest,
    ad_group_to_pinterest_payload,
    ad_to_pinterest_payload,
    campaign_from_pinterest,
    campaign_to_pinterest_payload,
    insights_from_pinterest,
)

DEFAULT_PAGE_SIZE = 25

_PINTEREST_OAUTH_URL = "https://www.pinterest.com/oauth/"

INSIGHTS_COLUMNS = [
    "SPEND_IN_DOLLAR",
    "IMPRESSION_1",
    "CLICKTHROUGH_1",
    "CTR",
    "ECPC_IN_DOLLAR",
    "TOTAL_CONVERSIONS",
]


class PinterestAdsAdapter(AdsPort, OAuthCapability):
    """
    Pinterest API v5 ads adapter.

    Implements AdsPort: campaign/ad group/ad CRUD + status changes with
    bookmark cursor pagination, and the universal insights interface via the
    synchronous analytics endpoints (granularity TOTAL). Writes use v5
    bulk-style endpoints — list bodies of one object — and map the returned
    item straight back to a DTO, so no re-fetch is needed.

    Implements OAuthCapability: authorization-code flow against
    https://www.pinterest.com/oauth/ with Basic-auth (client_id:client_secret)
    token and refresh calls; refresh responses that omit the refresh token
    keep the incoming one.
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
        self.config = config or {}
        self.ad_account_id = str(credentials.get("ad_account_id", ""))
        self._client_id = credentials.get("client_id", "")
        self._client_secret = credentials.get("client_secret", "")

        if http_client is None:
            http_client = ResilientHttpClient(
                base_url=manifest.base_url,
                auth=BearerAuth(token=credentials.get("token", "")),
                provider_name=manifest.name,
            )

        self.client = PinterestAdsClient(http_client=http_client, ad_account_id=self.ad_account_id)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        if self._client_id and self._client_secret:
            # OAuth-flow-only adapter: app credentials alone are enough to run the flow.
            return True
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0 and bool(self.credentials.get("token"))

    def test_connection(self) -> ConnectionTestResult:
        try:
            account = self.client.get_ad_account()
            name = account.get("name", "")
            return ConnectionTestResult(
                success=True,
                message=f"Connected to Pinterest ad account '{name}' ({self.ad_account_id})",
                details=account,
            )
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── OAuthCapability ──

    def _basic_auth_header(self) -> dict:
        encoded = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _token_response(self, data: dict, fallback_refresh_token: str = "") -> OAuthTokens:
        access_token = data.get("access_token", "")
        return OAuthTokens(
            access_token=access_token,
            # Pinterest refresh responses may omit the refresh token — keep the incoming one.
            refresh_token=data.get("refresh_token") or fallback_refresh_token,
            expires_in=data.get("expires_in"),
            token_type=data.get("token_type", "Bearer"),
            extra={
                "credentials": {
                    "token": access_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                "scope": data.get("scope", ""),
            },
        )

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        scopes = self.manifest.auth.oauth.scopes if self.manifest.auth.oauth else []
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
            "state": state,
        }
        return f"{_PINTEREST_OAUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            "oauth/token",
            headers=self._basic_auth_header(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        return self._token_response(response if isinstance(response, dict) else {})

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        response = self.client.http.call(
            "POST",
            "oauth/token",
            headers=self._basic_auth_header(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        data = response if isinstance(response, dict) else {}
        return self._token_response(data, fallback_refresh_token=refresh_token)

    def list_ad_accounts(self, access_token: str | None = None) -> list[dict]:
        """List the ad accounts the token can access, for the connect-flow account picker.

        Helper for completing the OAuth flow (not part of OAuthCapability):
        the adapter's http client authenticates with the stored ``token``
        credential — pass ``access_token`` (e.g. the fresh token from
        ``exchange_code_for_token``) to override it with a Bearer header on
        this call only. Let the user pick an account and store its
        ``ad_account_id`` as the ``ad_account_id`` credential.

        Returns a list of ``{"ad_account_id", "name", "currency", "country"}`` dicts.
        """
        kwargs: dict = {"params": {"page_size": DEFAULT_PAGE_SIZE}}
        if access_token:
            kwargs["headers"] = {"Authorization": f"Bearer {access_token}"}
        response = self.client.http.call("GET", "ad_accounts", **kwargs)
        data = response if isinstance(response, dict) else {}
        return [
            {
                "ad_account_id": account.get("id", ""),
                "name": account.get("name", ""),
                "currency": account.get("currency", ""),
                "country": account.get("country", ""),
            }
            for account in data.get("items", [])
        ]

    # ── Shared helpers ──

    @staticmethod
    def _paginate(response: dict, mapper) -> PaginatedResult:
        """Build a PaginatedResult from a v5 bookmark envelope {"items": [...], "bookmark": ...}."""
        bookmark = response.get("bookmark") or None
        return PaginatedResult(
            items=[mapper(row) for row in response.get("items", [])],
            cursor=bookmark,
            has_more=bool(bookmark),
        )

    @staticmethod
    def _first_item(response: dict, entity: str) -> dict:
        """Extract the single written object from a bulk-style {"items": [...]} response."""
        items = response.get("items") or []
        if not items:
            raise PermanentProviderError(f"Pinterest {entity} write returned no items.")
        return check_item(items[0])

    # ── Campaigns ──

    def list_campaigns(self, cursor: str | None = None) -> PaginatedResult[AdCampaign]:
        response = self.client.list_campaigns(page_size=DEFAULT_PAGE_SIZE, bookmark=cursor)
        return self._paginate(response, campaign_from_pinterest)

    def get_campaign(self, campaign_id: str) -> AdCampaign:
        return campaign_from_pinterest(self.client.get_campaign(campaign_id))

    def create_campaign(self, campaign: AdCampaign) -> AdCampaign:
        payload = campaign_to_pinterest_payload(campaign.model_dump(exclude={"provider_meta"}))
        response = self.client.create_campaigns([payload])
        return campaign_from_pinterest(self._first_item(response, "campaign"))

    def update_campaign(self, campaign_id: str, changes: dict) -> AdCampaign:
        payload = campaign_to_pinterest_payload(changes)
        payload["id"] = campaign_id
        response = self.client.update_campaigns([payload])
        return campaign_from_pinterest(self._first_item(response, "campaign"))

    def set_campaign_status(self, campaign_id: str, status: AdEntityStatus) -> AdCampaign:
        return self.update_campaign(campaign_id, {"status": status})

    # ── Ad groups ──

    def list_ad_groups(self, campaign_id: str | None = None, cursor: str | None = None) -> PaginatedResult[AdGroup]:
        response = self.client.list_ad_groups(
            page_size=DEFAULT_PAGE_SIZE,
            bookmark=cursor,
            campaign_ids=[campaign_id] if campaign_id else None,
        )
        return self._paginate(response, ad_group_from_pinterest)

    def get_ad_group(self, ad_group_id: str) -> AdGroup:
        return ad_group_from_pinterest(self.client.get_ad_group(ad_group_id))

    def create_ad_group(self, ad_group: AdGroup) -> AdGroup:
        payload = ad_group_to_pinterest_payload(ad_group.model_dump(exclude={"provider_meta"}))
        response = self.client.create_ad_groups([payload])
        return ad_group_from_pinterest(self._first_item(response, "ad group"))

    def update_ad_group(self, ad_group_id: str, changes: dict) -> AdGroup:
        payload = ad_group_to_pinterest_payload(changes)
        payload["id"] = ad_group_id
        response = self.client.update_ad_groups([payload])
        return ad_group_from_pinterest(self._first_item(response, "ad group"))

    def set_ad_group_status(self, ad_group_id: str, status: AdEntityStatus) -> AdGroup:
        return self.update_ad_group(ad_group_id, {"status": status})

    # ── Ads ──

    def list_ads(self, ad_group_id: str | None = None, cursor: str | None = None) -> PaginatedResult[Ad]:
        response = self.client.list_ads(
            page_size=DEFAULT_PAGE_SIZE,
            bookmark=cursor,
            ad_group_ids=[ad_group_id] if ad_group_id else None,
        )
        return self._paginate(response, ad_from_pinterest)

    def get_ad(self, ad_id: str) -> Ad:
        return ad_from_pinterest(self.client.get_ad(ad_id))

    def create_ad(self, ad: Ad) -> Ad:
        payload = ad_to_pinterest_payload(ad.model_dump(exclude={"provider_meta"}), for_create=True)
        response = self.client.create_ads([payload])
        return ad_from_pinterest(self._first_item(response, "ad"))

    def update_ad(self, ad_id: str, changes: dict) -> Ad:
        payload = ad_to_pinterest_payload(changes)
        payload["id"] = ad_id
        response = self.client.update_ads([payload])
        return ad_from_pinterest(self._first_item(response, "ad"))

    def set_ad_status(self, ad_id: str, status: AdEntityStatus) -> Ad:
        return self.update_ad(ad_id, {"status": status})

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
            "start_date": since.strftime("%Y-%m-%d"),
            "end_date": until.strftime("%Y-%m-%d"),
            "columns": INSIGHTS_COLUMNS,
            "granularity": "TOTAL",
        }

        if level == AdInsightsLevel.ACCOUNT:
            rows = self.client.get_account_analytics(params)
        else:
            fetch, filter_param = {
                AdInsightsLevel.CAMPAIGN: (self.client.get_campaign_analytics, "campaign_ids"),
                AdInsightsLevel.AD_GROUP: (self.client.get_ad_group_analytics, "ad_group_ids"),
                AdInsightsLevel.AD: (self.client.get_ad_analytics, "ad_ids"),
            }[level]
            if entity_id:
                params[filter_param] = [entity_id]
            rows = fetch(params)

        # The analytics endpoints return a bare list of row dicts.
        if isinstance(rows, dict):
            rows = rows.get("items", [])
        return [insights_from_pinterest(row, level) for row in rows or []]
