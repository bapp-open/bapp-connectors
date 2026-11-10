"""
LinkedIn Marketing API client — raw HTTP calls only, no business logic.

All paths are relative to https://api.linkedin.com/rest/. Account-scoped
collections live under adAccounts/{account_id}/. Every call carries the
Bearer token, the Restli protocol header, and the LinkedIn-Version header.

Restli finder parameters (search filters, ``List(...)`` values, analytics
``dateRange``) use Restli 2.0 syntax that ``requests`` ``params=`` would
over-encode, so query strings are built manually and appended to the path.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import quote

from bapp_connectors.core.ai import ai_method
from bapp_connectors.providers.ads.linkedin.errors import check_response

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


# Fixed metric list of the AI-agent analytics read (``analytics`` itself joins any params verbatim).
AI_ANALYTICS_FIELDS = (
    "impressions,clicks,costInLocalCurrency,externalWebsiteConversions,landingPageClicks,"
    "totalEngagements,videoViews,oneClickLeads,dateRange,pivotValues"
)
AnalyticsPivot = Literal["ACCOUNT", "CAMPAIGN_GROUP", "CAMPAIGN", "CREATIVE"]
TimeGranularity = Literal["ALL", "DAILY", "MONTHLY"]


def _restli_day(value: date) -> str:
    return f"(year:{value.year},month:{value.month},day:{value.day})"


def encode_urn(urn: str) -> str:
    """Percent-encode a URN for use inside a path segment or a Restli List(...)."""
    return quote(str(urn), safe="")


class LinkedInAdsClient:
    """
    Low-level LinkedIn Marketing API client.

    This class only handles HTTP calls and response shaping. Data
    normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, access_token: str, account_id: str, version: str):
        self.http = http_client
        self.access_token = access_token
        self.account_id = str(account_id)
        self.version = version

    @property
    def account_urn(self) -> str:
        return f"urn:li:sponsoredAccount:{self.account_id}"

    def _headers(self, extra: dict | None = None) -> dict:
        """Build the per-call LinkedIn auth + protocol headers."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.version,
        }
        if extra:
            headers.update(extra)
        return headers

    def _account_path(self, suffix: str) -> str:
        return f"adAccounts/{self.account_id}/{suffix}"

    def _get(self, path: str) -> dict:
        response = self.http.call("GET", path, headers=self._headers())
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _with_paging(query: str, page_token: str | None, page_size: int | None) -> str:
        if page_size is not None:
            query += f"&pageSize={page_size}"
        if page_token:
            query += f"&pageToken={quote(str(page_token), safe='')}"
        return query

    # ── Reads ──

    @ai_method("read", "List the ad account's campaign groups. Paginate with metadata.nextPageToken.")
    def list_campaign_groups(
        self, page_token: Annotated[str, "free_text"] | None = None, page_size: int | None = None
    ) -> dict:
        """GET the adCampaignGroups search finder for the account."""
        query = self._with_paging("q=search", page_token, page_size)
        return self._get(self._account_path(f"adCampaignGroups?{query}"))

    @ai_method("read", "List the ad account's campaigns, optionally of one campaign group (its URN).")
    def list_campaigns(
        self,
        campaign_group_urn: str | None = None,
        page_token: Annotated[str, "free_text"] | None = None,
        page_size: int | None = None,
    ) -> dict:
        """GET the adCampaigns search finder, optionally filtered to one campaign group."""
        query = "q=search"
        if campaign_group_urn:
            query += f"&search=(campaignGroup:(values:List({encode_urn(campaign_group_urn)})))"
        query = self._with_paging(query, page_token, page_size)
        return self._get(self._account_path(f"adCampaigns?{query}"))

    @ai_method("read", "List the ad account's creatives, optionally of one campaign (its URN).")
    def list_creatives(
        self,
        campaign_urn: str | None = None,
        page_token: Annotated[str, "free_text"] | None = None,
        page_size: int | None = None,
    ) -> dict:
        """GET the creatives criteria finder, optionally filtered to one campaign."""
        query = "q=criteria"
        if campaign_urn:
            query += f"&campaigns=List({encode_urn(campaign_urn)})"
        query = self._with_paging(query, page_token, page_size)
        return self._get(self._account_path(f"creatives?{query}"))

    @ai_method("read", "Get one campaign group by its numeric ID.")
    def get_campaign_group(self, campaign_group_id: str) -> dict:
        return self._get(self._account_path(f"adCampaignGroups/{campaign_group_id}"))

    @ai_method("read", "Get one campaign by its numeric ID.")
    def get_campaign(self, campaign_id: str) -> dict:
        return self._get(self._account_path(f"adCampaigns/{campaign_id}"))

    @ai_method("read", "Get one creative by its URN (urn:li:sponsoredCreative:...).")
    def get_creative(self, creative_urn: str) -> dict:
        """GET one creative — creatives are addressed by their (percent-encoded) URN."""
        return self._get(self._account_path(f"creatives/{encode_urn(creative_urn)}"))

    # ── Writes ──

    def _create(self, path: str, payload: dict) -> str:
        """POST a new entity and return its id from the ``x-restli-id`` header.

        LinkedIn creates return an empty 201 body; the created id (numeric or
        a full URN, depending on the resource) travels in the header, hence
        ``direct_response=True``.
        """
        response = self.http.call("POST", path, json=payload, headers=self._headers(), direct_response=True)
        check_response(response)
        return str(response.headers.get("x-restli-id", ""))

    @ai_method("write", "Create a campaign group in the ad account.")
    def create_campaign_group(self, payload: dict) -> str:
        return self._create(self._account_path("adCampaignGroups"), payload)

    @ai_method("write", "Create a campaign in the ad account.")
    def create_campaign(self, payload: dict) -> str:
        return self._create(self._account_path("adCampaigns"), payload)

    @ai_method("write", "Create a creative in the ad account.")
    def create_creative(self, payload: dict) -> str:
        return self._create(self._account_path("creatives"), payload)

    def _partial_update(self, path: str, fields: dict) -> None:
        """POST a Restli PARTIAL_UPDATE patch that ``$set``s the given fields."""
        self.http.call(
            "POST",
            path,
            json={"patch": {"$set": fields}},
            headers=self._headers({"X-RestLi-Method": "PARTIAL_UPDATE"}),
        )

    @ai_method("write", "Update fields of a campaign group.")
    def update_campaign_group(self, campaign_group_id: str, fields: dict) -> None:
        self._partial_update(self._account_path(f"adCampaignGroups/{campaign_group_id}"), fields)

    @ai_method("write", "Update fields of a campaign.")
    def update_campaign(self, campaign_id: str, fields: dict) -> None:
        self._partial_update(self._account_path(f"adCampaigns/{campaign_id}"), fields)

    @ai_method("write", "Update fields of a creative.")
    def update_creative(self, creative_urn: str, fields: dict) -> None:
        self._partial_update(self._account_path(f"creatives/{encode_urn(creative_urn)}"), fields)

    # ── Account & analytics ──

    @ai_method("read", "The connected LinkedIn ad account: name, status, currency, type.")
    def get_account(self) -> dict:
        return self._get(f"adAccounts/{self.account_id}")

    def search_ad_accounts(self, access_token: str | None = None) -> dict:
        """GET the adAccounts search finder — every ad account the token can access.

        ``access_token`` overrides the client's stored token for this call
        only (used by connect-flow helpers that run before credentials are
        stored).
        """
        headers = self._headers()
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        response = self.http.call("GET", "adAccounts?q=search", headers=headers)
        return response if isinstance(response, dict) else {}

    def analytics(self, params: dict) -> dict:
        """GET adAnalytics with a manually built query string.

        ``params`` values must already be Restli-encoded (List(...), dateRange
        record syntax, percent-encoded URNs) — they are joined verbatim.
        """
        query = "&".join(f"{key}={value}" for key, value in params.items())
        return self._get(f"adAnalytics?{query}")

    @ai_method(
        "read",
        "Ad analytics of the ad account (impressions, clicks, spend, conversions, engagement) between two "
        "dates (YYYY-MM-DD), one row per 'pivot' entity, optionally only for one campaign group or campaign "
        "(numeric IDs).",
    )
    def get_analytics_report(
        self,
        start_date: date,
        end_date: date | None = None,
        pivot: AnalyticsPivot = "CAMPAIGN",
        time_granularity: TimeGranularity = "ALL",
        campaign_group_id: str | None = None,
        campaign_id: str | None = None,
    ) -> dict:
        end = end_date or date.today()
        params: dict = {
            "q": "analytics",
            "pivot": pivot,
            "dateRange": f"(start:{_restli_day(start_date)},end:{_restli_day(end)})",
            "timeGranularity": time_granularity,
            "accounts": f"List({encode_urn(self.account_urn)})",
            "fields": AI_ANALYTICS_FIELDS,
        }
        if campaign_group_id:
            params["campaignGroups"] = f"List({encode_urn(f'urn:li:sponsoredCampaignGroup:{campaign_group_id}')})"
        if campaign_id:
            params["campaigns"] = f"List({encode_urn(f'urn:li:sponsoredCampaign:{campaign_id}')})"
        return self.analytics(params)
