"""
Google Ads REST API v17 client — raw HTTP calls only, no business logic.

Talks to the REST (not gRPC) surface of the Google Ads API:
    POST customers/{customer_id}/googleAds:search   — GAQL queries
    POST customers/{customer_id}/{resource}:mutate  — create/update/remove operations

Auth is an OAuth2 Bearer access token plus a developer-token header on every
request. OAuth token refresh is handled outside the adapter — pass a valid
``access_token``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Annotated

from bapp_connectors.core.ai import ai_method
from bapp_connectors.core.errors import ValidationError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)

# GAQL resources an AI agent may query through ``run_report``: campaign structure and performance
# views. Account administration (users, invitations, links, billing) is left out, and so is
# ``asset``: a lead-form asset carries its webhook's ``google_secret``.
AI_GAQL_RESOURCES = frozenset(
    {
        "customer",
        "campaign",
        "campaign_budget",
        "campaign_criterion",
        "ad_group",
        "ad_group_ad",
        "ad_group_criterion",
        "ad_group_ad_asset_view",
        "asset_group",
        "bidding_strategy",
        "conversion_action",
        "label",
        "user_list",
        "keyword_view",
        "search_term_view",
        "landing_page_view",
        "geographic_view",
        "gender_view",
        "age_range_view",
        "shopping_performance_view",
        "display_keyword_view",
    }
)
_GAQL_SELECT = re.compile(r"^\s*SELECT\s", re.IGNORECASE)
_GAQL_FROM = re.compile(r"\bFROM\s+([A-Za-z_]+)", re.IGNORECASE)
# Field names that reach a secret through an attributed resource (lead-form webhook delivery).
_GAQL_FORBIDDEN = re.compile(r"google_secret|webhook|lead_form", re.IGNORECASE)


def check_ai_gaql(query: str) -> str:
    """The GAQL query if it is a single SELECT over an allowed resource, else ValidationError."""
    if not _GAQL_SELECT.match(query or ""):
        raise ValidationError("The query must be a GAQL SELECT statement.")
    if _GAQL_FORBIDDEN.search(query):
        raise ValidationError("The query may not select lead-form or webhook fields.")
    resources = _GAQL_FROM.findall(query)
    if len(resources) != 1:
        raise ValidationError("The query must have exactly one FROM clause.")
    resource = resources[0].lower()
    if resource not in AI_GAQL_RESOURCES:
        raise ValidationError(
            f"Querying '{resource}' is not allowed; use one of: {', '.join(sorted(AI_GAQL_RESOURCES))}."
        )
    return query


def sanitize_customer_id(value: str) -> str:
    """Strip dashes and any other non-digit characters ("123-456-7890" -> "1234567890")."""
    return "".join(ch for ch in str(value) if ch.isdigit())


class GoogleAdsClient:
    """
    Low-level Google Ads REST API client.

    This class only handles HTTP calls and response shaping.
    Data normalization happens in the adapter via mappers.
    """

    def __init__(
        self,
        http_client: ResilientHttpClient,
        developer_token: str,
        access_token: str,
        customer_id: str,
        login_customer_id: str = "",
    ):
        self.http = http_client
        self.developer_token = developer_token
        self.access_token = access_token
        self.customer_id = sanitize_customer_id(customer_id)
        self.login_customer_id = sanitize_customer_id(login_customer_id)

    def _headers(self) -> dict:
        """Build the per-call Google Ads auth headers."""
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        return headers

    def search(self, query: str, page_token: str | None = None) -> dict:
        """googleAds:search — run a GAQL query.

        Returns the raw response dict with ``results`` normalized to a list
        (Google omits the key when a query matches no rows) and an optional
        ``nextPageToken``.
        """
        payload: dict = {"query": query}
        if page_token:
            payload["pageToken"] = page_token
        response = self.http.call(
            "POST",
            f"customers/{self.customer_id}/googleAds:search",
            json=payload,
            headers=self._headers(),
        )
        if not isinstance(response, dict):
            return {"results": []}
        response.setdefault("results", [])
        return response

    @ai_method(
        "read",
        "Run a Google Ads Query Language (GAQL) SELECT on the connected customer, e.g. "
        '"SELECT campaign.id, campaign.name, metrics.clicks, metrics.cost_micros FROM campaign '
        'WHERE segments.date DURING LAST_30_DAYS". FROM must be one of: ' + ", ".join(sorted(AI_GAQL_RESOURCES)) + ". "
        "Paginate with nextPageToken as page_token.",
    )
    def run_report(
        self,
        query: Annotated[str, "free_text"],
        page_token: Annotated[str, "free_text"] | None = None,
    ) -> dict:
        return self.search(check_ai_gaql(query), page_token=page_token)

    def mutate(self, resource: str, operations: list[dict]) -> dict:
        """{resource}:mutate — apply create/update/remove operations.

        ``resource`` is one of: campaignBudgets, campaigns, adGroups, adGroupAds, assets.
        Returns {"results": [{"resourceName": ...}, ...]}.
        """
        response = self.http.call(
            "POST",
            f"customers/{self.customer_id}/{resource}:mutate",
            json={"operations": operations},
            headers=self._headers(),
        )
        return response if isinstance(response, dict) else {}
