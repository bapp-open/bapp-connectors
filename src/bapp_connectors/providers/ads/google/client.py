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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient

logger = logging.getLogger(__name__)


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
