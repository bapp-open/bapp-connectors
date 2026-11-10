"""
Meta Marketing API client — raw HTTP calls only, no business logic.

All paths are relative to https://graph.facebook.com/v19.0/. Account-scoped
edges live under act_{ad_account_id}/. Auth (Bearer token) is applied by the
underlying ResilientHttpClient.
"""

from __future__ import annotations

import json
import logging
from datetime import date  # noqa: TC003 -- runtime: get_type_hints on the AI reads
from typing import TYPE_CHECKING, Annotated, Any, Literal

from bapp_connectors.core.ai import ai_method
from bapp_connectors.providers.ads.facebook.errors import check_payload

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# Fixed field lists of the AI-agent reads. The generic ``list_edge``/``get_object``/``get_insights``
# take any path and any ``fields`` (``fields=access_token`` on a Page returns its Page token), so
# they are never offered to an agent; these wrappers pin both the edge and the fields.
AI_ACCOUNT_FIELDS = (
    "id,account_id,name,account_status,currency,timezone_name,amount_spent,balance,spend_cap,business_name"
)
AI_CAMPAIGN_FIELDS = (
    "id,name,status,effective_status,objective,daily_budget,lifetime_budget,start_time,stop_time,"
    "created_time,updated_time"
)
AI_ADSET_FIELDS = (
    "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,bid_amount,"
    "billing_event,optimization_goal,targeting,start_time,end_time"
)
AI_AD_FIELDS = "id,name,adset_id,campaign_id,status,effective_status,creative{id,name,title,body,thumbnail_url}"
AI_CREATIVE_FIELDS = "id,name,status,title,body,image_url,thumbnail_url,call_to_action_type"
AI_AUDIENCE_FIELDS = (
    "id,name,description,subtype,approximate_count_lower_bound,approximate_count_upper_bound,"
    "delivery_status,operation_status,time_created,time_updated"
)
AI_INSIGHTS_FIELDS = (
    "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,impressions,clicks,spend,ctr,cpc,cpm,"
    "reach,frequency,actions,action_values,account_currency,date_start,date_stop"
)

InsightsLevel = Literal["account", "campaign", "adset", "ad"]
DatePreset = Literal[
    "today",
    "yesterday",
    "last_7d",
    "last_14d",
    "last_30d",
    "last_90d",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "maximum",
]
TimeIncrement = Literal["daily", "monthly", "all_days"]
_TIME_INCREMENT = {"daily": "1", "monthly": "monthly", "all_days": "all_days"}


class MetaAdsClient:
    """
    Low-level Meta Marketing API client.

    This class only handles HTTP calls and response parsing. Data
    normalization happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, ad_account_id: str):
        self.http = http_client
        self.ad_account_id = ad_account_id

    def account_path(self, edge: str) -> str:
        """Build an account-scoped edge path, e.g. ``act_123/campaigns``."""
        return f"act_{self.ad_account_id}/{edge}"

    def _parse(self, response: Any) -> Any:
        """Raise framework errors for Graph API error payloads (which can arrive with HTTP 200)."""
        if isinstance(response, dict):
            check_payload(response)
        return response

    # ── Reads ──

    def list_edge(
        self,
        path: str,
        fields: str,
        limit: int | None = None,
        after: str | None = None,
        filtering: list[dict] | None = None,
    ) -> dict:
        """GET a paginated edge (campaigns, adsets, ads, ...)."""
        params: dict = {"fields": fields}
        if limit is not None:
            params["limit"] = limit
        if after:
            params["after"] = after
        if filtering:
            params["filtering"] = json.dumps(filtering)
        return self._parse(self.http.call("GET", path, params=params))

    def get_object(self, object_id: str, fields: str) -> dict:
        """GET a single Graph object by ID."""
        return self._parse(self.http.call("GET", object_id, params={"fields": fields}))

    def get_insights(self, object_id: str, params: dict) -> dict:
        """GET the insights edge of an object."""
        return self._parse(self.http.call("GET", f"{object_id}/insights", params=params))

    # ── AI-agent reads (fixed edges and fields) ──

    def _account_edge(self, edge: str, fields: str, limit: int | None, after: str | None, filtering=None) -> dict:
        return self.list_edge(self.account_path(edge), fields=fields, limit=limit, after=after, filtering=filtering)

    @ai_method("read", "The connected Meta ad account: name, status, currency, timezone, amount spent, spend cap.")
    def get_ad_account_info(self) -> dict:
        return self.get_object(f"act_{self.ad_account_id}", fields=AI_ACCOUNT_FIELDS)

    @ai_method("read", "List the ad account's campaigns. Paginate with the 'after' cursor from paging.cursors.")
    def list_account_campaigns(
        self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return self._account_edge("campaigns", AI_CAMPAIGN_FIELDS, limit, after)

    @ai_method("read", "List the ad account's ad sets, optionally only those of one campaign.")
    def list_account_ad_sets(
        self, campaign_id: str | None = None, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        filtering = [{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}] if campaign_id else None
        return self._account_edge("adsets", AI_ADSET_FIELDS, limit, after, filtering)

    @ai_method("read", "List the ad account's ads, optionally only those of one ad set.")
    def list_account_ads(
        self, ad_set_id: str | None = None, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        filtering = [{"field": "adset.id", "operator": "EQUAL", "value": ad_set_id}] if ad_set_id else None
        return self._account_edge("ads", AI_AD_FIELDS, limit, after, filtering)

    @ai_method("read", "List the ad account's ad creatives (name, title, body, image).")
    def list_account_creatives(
        self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return self._account_edge("adcreatives", AI_CREATIVE_FIELDS, limit, after)

    @ai_method("read", "List the ad account's custom audiences with their approximate size and status.")
    def list_account_custom_audiences(
        self, limit: int | None = None, after: Annotated[str, "free_text"] | None = None
    ) -> dict:
        return self._account_edge("customaudiences", AI_AUDIENCE_FIELDS, limit, after)

    @ai_method("read", "Get one campaign by its ID.")
    def get_campaign_info(self, campaign_id: str) -> dict:
        return self.get_object(campaign_id, fields=AI_CAMPAIGN_FIELDS)

    @ai_method("read", "Get one ad set by its ID.")
    def get_ad_set_info(self, ad_set_id: str) -> dict:
        return self.get_object(ad_set_id, fields=AI_ADSET_FIELDS)

    @ai_method("read", "Get one ad by its ID.")
    def get_ad_info(self, ad_id: str) -> dict:
        return self.get_object(ad_id, fields=AI_AD_FIELDS)

    @ai_method(
        "read",
        "Performance report (impressions, clicks, spend, CTR, CPC, CPM, reach, actions) of the ad account, "
        "or of one campaign/ad set/ad when object_id is given, broken down by 'level'. Pick a date_preset or "
        "since/until (YYYY-MM-DD); time_increment splits rows per day or month.",
    )
    def get_insights_report(
        self,
        object_id: str | None = None,
        level: InsightsLevel = "account",
        date_preset: DatePreset | None = None,
        since: date | None = None,
        until: date | None = None,
        time_increment: TimeIncrement | None = None,
        limit: int | None = None,
        after: Annotated[str, "free_text"] | None = None,
    ) -> dict:
        params: dict = {"level": level, "fields": AI_INSIGHTS_FIELDS}
        if since or until:
            time_range = {}
            if since:
                time_range["since"] = since.isoformat()
            if until:
                time_range["until"] = until.isoformat()
            params["time_range"] = json.dumps(time_range)
        elif date_preset:
            params["date_preset"] = date_preset
        if time_increment:
            params["time_increment"] = _TIME_INCREMENT[time_increment]
        if limit is not None:
            params["limit"] = limit
        if after:
            params["after"] = after
        return self.get_insights(object_id or f"act_{self.ad_account_id}", params)

    # ── Writes ──

    def create(self, path: str, payload: dict) -> dict:
        """POST a new object to an edge. Returns the Graph response (usually {"id": ...})."""
        return self._parse(self.http.call("POST", path, json=payload))

    def update(self, object_id: str, payload: dict) -> dict:
        """POST field updates to an existing object."""
        return self._parse(self.http.call("POST", object_id, json=payload))

    # ── Media & creatives ──

    def upload_image(self, files: dict | None = None, payload: dict | None = None) -> dict:
        """POST an ad image to act_{id}/adimages.

        Pass ``files`` for a multipart upload, or ``payload`` for a JSON body
        (e.g. ``{"bytes": <base64>}``). Response: ``{"images": {<name>: {"hash": ..., "url": ...}}}``.
        """
        kwargs: dict = {}
        if files is not None:
            kwargs["files"] = files
        if payload is not None:
            kwargs["json"] = payload
        return self._parse(self.http.call("POST", self.account_path("adimages"), **kwargs))

    def upload_video(self, payload: dict | None = None, files: dict | None = None) -> dict:
        """POST an ad video to act_{id}/advideos.

        Pass ``payload`` for a JSON body (e.g. ``{"file_url": ...}``), or
        ``files`` for a multipart upload of the ``source`` field. Response: ``{"id": ...}``.
        """
        kwargs: dict = {}
        if payload is not None:
            kwargs["json"] = payload
        if files is not None:
            kwargs["files"] = files
        return self._parse(self.http.call("POST", self.account_path("advideos"), **kwargs))

    @ai_method("write", "Create an ad creative in the ad account from a Marketing API creative payload.")
    def create_creative_object(self, payload: dict) -> dict:
        """POST a new ad creative to act_{id}/adcreatives. Returns ``{"id": ...}``."""
        return self._parse(self.http.call("POST", self.account_path("adcreatives"), json=payload))
