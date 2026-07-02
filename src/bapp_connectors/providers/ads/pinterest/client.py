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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


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

    def get_ad_account(self) -> dict:
        """GET ad_accounts/{id} — the connected ad account."""
        return self._get(self.account_path())

    # ── Campaigns ──

    def list_campaigns(
        self,
        page_size: int = 25,
        bookmark: str | None = None,
        campaign_ids: list[str] | None = None,
    ) -> dict:
        """GET ad_accounts/{id}/campaigns — bookmark-paginated list."""
        return self._get(
            self.account_path("campaigns"),
            {"page_size": page_size, "bookmark": bookmark, "campaign_ids": campaign_ids},
        )

    def get_campaign(self, campaign_id: str) -> dict:
        """GET ad_accounts/{id}/campaigns/{campaign_id} — a single campaign."""
        return self._get(self.account_path(f"campaigns/{campaign_id}"))

    def create_campaigns(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/campaigns — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("campaigns"), json=payloads)

    def update_campaigns(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/campaigns — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("campaigns"), json=payloads)

    # ── Ad groups ──

    def list_ad_groups(
        self,
        page_size: int = 25,
        bookmark: str | None = None,
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

    def get_ad_group(self, ad_group_id: str) -> dict:
        """GET ad_accounts/{id}/ad_groups/{ad_group_id} — a single ad group."""
        return self._get(self.account_path(f"ad_groups/{ad_group_id}"))

    def create_ad_groups(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/ad_groups — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("ad_groups"), json=payloads)

    def update_ad_groups(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/ad_groups — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("ad_groups"), json=payloads)

    # ── Ads ──

    def list_ads(
        self,
        page_size: int = 25,
        bookmark: str | None = None,
        ad_group_ids: list[str] | None = None,
        ad_ids: list[str] | None = None,
    ) -> dict:
        """GET ad_accounts/{id}/ads — bookmark-paginated list."""
        return self._get(
            self.account_path("ads"),
            {"page_size": page_size, "bookmark": bookmark, "ad_group_ids": ad_group_ids, "ad_ids": ad_ids},
        )

    def get_ad(self, ad_id: str) -> dict:
        """GET ad_accounts/{id}/ads/{ad_id} — a single ad."""
        return self._get(self.account_path(f"ads/{ad_id}"))

    def create_ads(self, payloads: list[dict]) -> dict:
        """POST ad_accounts/{id}/ads — bulk-style list body, returns {"items": [...]}."""
        return self.http.call("POST", self.account_path("ads"), json=payloads)

    def update_ads(self, payloads: list[dict]) -> dict:
        """PATCH ad_accounts/{id}/ads — list body of {"id", ...changes}, returns {"items": [...]}."""
        return self.http.call("PATCH", self.account_path("ads"), json=payloads)

    # ── Analytics ──

    def get_account_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/analytics — account-level rows."""
        return self._get(self.account_path("analytics"), params)

    def get_campaign_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/campaigns/analytics — one row per campaign."""
        return self._get(self.account_path("campaigns/analytics"), params)

    def get_ad_group_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/ad_groups/analytics — one row per ad group."""
        return self._get(self.account_path("ad_groups/analytics"), params)

    def get_ad_analytics(self, params: dict) -> Any:
        """GET ad_accounts/{id}/ads/analytics — one row per ad."""
        return self._get(self.account_path("ads/analytics"), params)
