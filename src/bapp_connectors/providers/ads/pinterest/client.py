"""
Pinterest API v5 client — raw HTTP calls only, no business logic.

All paths are relative to https://api.pinterest.com/v5/ and account-scoped
resources live under ad_accounts/{ad_account_id}/. Auth (Bearer token) is
applied by the underlying ResilientHttpClient.

Write endpoints are v5 bulk-style: POST (create) and PATCH (update) take a
LIST body of objects and return ``{"items": [{...}]}``. List endpoints
paginate with ``page_size`` + ``bookmark`` and filter with comma-joined ID
parameters. Error bodies arrive with matching HTTP statuses, so error
classification is handled by the HTTP layer.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Annotated, Any

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


# Query keys an AI agent may pass to the analytics reads (all values are dates, metric names,
# granularity, attribution windows or entity ID lists; the account comes from the path).
AI_ANALYTICS_KEYS = (
    "start_date",
    "end_date",
    "columns",
    "granularity",
    "click_window_days",
    "engagement_window_days",
    "view_window_days",
    "conversion_report_time",
    "campaign_ids",
    "ad_group_ids",
    "ad_ids",
)
_ANALYTICS_HELP = (
    " params: start_date, end_date (YYYY-MM-DD), columns (list, e.g. SPEND_IN_DOLLAR, IMPRESSION_1, "
    "CLICKTHROUGH_1, CTR, TOTAL_CONVERSIONS), granularity (TOTAL, DAY, HOUR, WEEK, MONTH)"
)


def _plain_id(value: str, what: str) -> str:
    """An id about to go into a path: letters, digits, ``_`` and ``-`` only (real Pinterest ads ids
    are numeric; the adapter's callers and fixtures also use short opaque ids, so digits-only would
    change adapter behaviour). Refuses ``&``, ``%``, ``:``, ``(``, ``,`` and the like."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValidationError(f"{what} is not a valid Pinterest id: {value!r}.")
    return value


class PinterestAdsClient:
    """
    Low-level Pinterest API v5 ads client.

    This class only handles HTTP calls and query encoding. Data normalization
    happens in the adapter via mappers.
    """

    def __init__(self, http_client: ResilientHttpClient, ad_account_id: str):
        self.http = http_client
        self.ad_account_id = ad_account_id

    def account_path(self, edge: str = "") -> str:
        """Build an account-scoped path, e.g. ``ad_accounts/123/campaigns``."""
        base = f"ad_accounts/{self.ad_account_id}"
        return f"{base}/{edge}" if edge else base

    def _get(self, path: str, params: dict | None = None) -> Any:
        """GET with None params dropped and list params comma-joined."""
        query = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            query[key] = ",".join(str(item) for item in value) if isinstance(value, list) else value
        return self.http.call("GET", path, params=query)

    # ── Ad account ──

    @ai_method("read", "The connected Pinterest ad account: name, owner, country, currency.")
    def get_ad_account(self) -> dict:
        """GET ad_accounts/{id} — the connected ad account."""
        return self._get(self.account_path())

    # ── Campaigns ──

    @ai_method("read", "List the ad account's campaigns. Paginate with the returned bookmark.")
    def list_campaigns(
        self,
        page_size: int = 25,
        bookmark: Annotated[str, "free_text"] | None = None,
        campaign_ids: list[str] | None = None,
    ) -> dict:
        """GET ad_accounts/{id}/campaigns — bookmark-paginated list."""
        return self._get(
            self.account_path("campaigns"),
            {"page_size": page_size, "bookmark": bookmark, "campaign_ids": campaign_ids},
        )

    @ai_method("read", "Get one campaign by its ID.")
    def get_campaign(self, campaign_id: str) -> dict:
        """GET ad_accounts/{id}/campaigns/{campaign_id} — a single campaign."""
        return self._get(self.account_path(f"campaigns/{_plain_id(campaign_id, 'campaign_id')}"))

    @ai_method("write", "Create campaigns in the ad account.")
    def create_campaigns(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/campaigns — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("campaigns"), json=payloads)

    @ai_method("write", "Update campaigns (each with its id).")
    def update_campaigns(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/campaigns — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("campaigns"), json=payloads)

    # ── Ad groups ──

    @ai_method("read", "List the ad account's ad groups, optionally filtered by campaign or ad group IDs.")
    def list_ad_groups(
        self,
        page_size: int = 25,
        bookmark: Annotated[str, "free_text"] | None = None,
        campaign_ids: list[str] | None = None,
        ad_group_ids: list[str] | None = None,
    ) -> dict:
        """GET ad_accounts/{id}/ad_groups — bookmark-paginated list."""
        return self._get(
            self.account_path("ad_groups"),
            {
                "page_size": page_size,
                "bookmark": bookmark,
                "campaign_ids": campaign_ids,
                "ad_group_ids": ad_group_ids,
            },
        )

    @ai_method("read", "Get one ad group by its ID.")
    def get_ad_group(self, ad_group_id: str) -> dict:
        """GET ad_accounts/{id}/ad_groups/{ad_group_id} — a single ad group."""
        return self._get(self.account_path(f"ad_groups/{_plain_id(ad_group_id, 'ad_group_id')}"))

    @ai_method("write", "Create ad groups in the ad account.")
    def create_ad_groups(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/ad_groups — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("ad_groups"), json=payloads)

    @ai_method("write", "Update ad groups (each with its id).")
    def update_ad_groups(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/ad_groups — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("ad_groups"), json=payloads)

    # ── Ads ──

    @ai_method("read", "List the ad account's ads, optionally filtered by ad group or ad IDs.")
    def list_ads(
        self,
        page_size: int = 25,
        bookmark: Annotated[str, "free_text"] | None = None,
        ad_group_ids: list[str] | None = None,
        ad_ids: list[str] | None = None,
    ) -> dict:
        """GET ad_accounts/{id}/ads — bookmark-paginated list."""
        return self._get(
            self.account_path("ads"),
            {"page_size": page_size, "bookmark": bookmark, "ad_group_ids": ad_group_ids, "ad_ids": ad_ids},
        )

    @ai_method("read", "Get one ad by its ID.")
    def get_ad(self, ad_id: str) -> dict:
        """GET ad_accounts/{id}/ads/{ad_id} — a single ad."""
        return self._get(self.account_path(f"ads/{_plain_id(ad_id, 'ad_id')}"))

    @ai_method("write", "Create ads in the ad account.")
    def create_ads(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/ads — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("ads"), json=payloads)

    @ai_method("write", "Update ads (each with its id).")
    def update_ads(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/ads — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("ads"), json=payloads)

    # ── Analytics ──

    @ai_method("read", "Account-level analytics." + _ANALYTICS_HELP + ".", allowed_keys={"params": AI_ANALYTICS_KEYS})
    def get_account_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/analytics — account-level rows."""
        return self._get(self.account_path("analytics"), params)

    @ai_method(
        "read",
        "Analytics per campaign." + _ANALYTICS_HELP + ", campaign_ids (required list).",
        allowed_keys={"params": AI_ANALYTICS_KEYS},
    )
    def get_campaign_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/campaigns/analytics — one row per campaign."""
        return self._get(self.account_path("campaigns/analytics"), params)

    @ai_method(
        "read",
        "Analytics per ad group." + _ANALYTICS_HELP + ", ad_group_ids (required list).",
        allowed_keys={"params": AI_ANALYTICS_KEYS},
    )
    def get_ad_group_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/ad_groups/analytics — one row per ad group."""
        return self._get(self.account_path("ad_groups/analytics"), params)

    @ai_method(
        "read",
        "Analytics per ad." + _ANALYTICS_HELP + ", ad_ids (required list).",
        allowed_keys={"params": AI_ANALYTICS_KEYS},
    )
    def get_ad_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/ads/analytics — one row per ad."""
        return self._get(self.account_path("ads/analytics"), params)
